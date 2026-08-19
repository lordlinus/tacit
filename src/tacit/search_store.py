"""Azure AI Search backend implementing the MemoryStore protocol.

Every project in the organization shares one index set. Latest state is
mergeOrUpload-ed into ``tacit-memories`` (key = project + path slug); every
mutation also uploads an immutable doc to ``tacit-versions`` and re-projects
the memory's sections into ``tacit-chunks``, the index searches run against.

Writes are always scoped to this store's project — a store can only ever
mutate its own team's memories. Reads of a single memory (``get``, ``list``,
``versions``, ``count``) are likewise project-scoped, because the sha
precondition contract is per-project. Only ``search`` deliberately crosses the
boundary, and only as far as ``scope`` and each memory's ``visibility`` allow.

Search asks for the semantic ranker (L2 reranking + extractive captions) and
falls back to plain BM25 when the service declines — semantic is a capacity
feature, so a store must stay usable without it. When an embedding deployment
is configured the same request also carries a vector query, making it a hybrid
one: Azure fuses the keyword and vector candidates with RRF and the semantic
ranker orders the result. Vectors degrade the same way semantic does, so an
index without them, or a tier that refuses them, still answers.

Note: AI Search indexing is near-real-time, not transactional — a doc becomes
searchable within seconds of upload. ``get`` uses the lookup API (consistent),
so the concurrency contract (sha preconditions) is not affected by search lag.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .azure_common import SEARCH_API_VERSION, build_credential, request_json, search_headers
from .config import Settings
from .models import (
    DEFAULT_PROJECT,
    HOME_PROJECT_BOOST,
    Memory,
    MemoryStatus,
    MemoryVersion,
    SearchHit,
    SearchScope,
    Visibility,
    doc_key,
)
from .ontology import Entity, Ontology
from .scope import Viewer, odata_quote, parse_scope, scope_filter
from .search_index import (
    ONTOLOGY_INDEX,
    SCORING_PROFILE,
    SEMANTIC_CONFIG,
    VECTOR_FIELD,
    index_names,
)
from .sections import Section, narrow, snippet, split_sections

SEARCH_FIELDS = "title,tags,heading,content,entity_vocabulary"
HIT_FIELDS = "path,project,team,section,heading,title,category,tags,content"

#: Azure AI Search semantically reranks only the top 50 candidates; asking for
#: more mixes reranker scores with raw BM25 ones in a single ordering.
SEMANTIC_RERANK_WINDOW = 50

__all__ = ["SearchStore", "chunk_key", "odata_quote"]


def chunk_key(project: str, path: str, section: str) -> str:
    return f"{doc_key(project, path)}--s-{section}"


class SearchStore:
    def __init__(
        self,
        settings: Settings,
        credential: Any | None = None,
        *,
        viewer: Viewer | None = None,
        embedder: Any | None = None,
    ) -> None:
        self._settings = settings
        self._endpoint = settings.search_endpoint.rstrip("/")
        self._credential = credential or build_credential(settings.auth_mode, settings.tenant_id)
        # Public per the MemoryStore protocol: MemoryService falls back to these
        # when not given an explicit project/team.
        self.project = settings.project
        self.team = settings.team
        self._project = self.project
        self._team = self.team
        self._viewer = viewer or Viewer(project=self.project, team=self.team)
        self._memories_index, self._versions_index, self._chunks_index = index_names()
        self._provisioned = False
        self._embedder = embedder if embedder is not None else settings.embedder(self._credential)
        self._vectors = settings.vectors_enabled
        self._ontology: Ontology | None = None

    # -- scoping ---------------------------------------------------------------

    def _own(self) -> str:
        """Filter restricting a query to this store's project."""
        return f"project eq '{odata_quote(self._project)}'"

    # -- vocabulary ------------------------------------------------------------

    def load_ontology(self, *, refresh: bool = False, strict: bool = False) -> Ontology:
        """The organization's controlled vocabulary, cached per store.

        Cached because it is read on every write and changes rarely. With
        ``strict=False`` an unreachable vocabulary degrades to no annotation
        rather than failing the write: memory is useful without it, and a
        vocabulary outage must not stop someone recording what they just
        learned. Callers that *derive a mutation* from the result must pass
        ``strict=True`` — see :meth:`save_ontology`.
        """
        if self._ontology is not None and not refresh:
            return self._ontology
        try:
            result = self._post(ONTOLOGY_INDEX, "/docs/search.post.search",
                                {"search": "*", "top": 1000})
            entities = [
                Entity.from_dict(_strip_metadata(d)) for d in (result or {}).get("value", [])
            ]
            self._ontology = Ontology(entities=entities)
        except Exception:  # noqa: BLE001 - vocabulary is an enhancement, not a dependency
            if strict:
                raise
            self._ontology = Ontology()
        return self._ontology

    def save_ontology(self, ontology: Ontology) -> int:
        """Replace the vocabulary. Callers re-chunk afterwards to apply it.

        Reads strictly: the set of entities to delete is ``existing - keep``, so
        a swallowed read error would make ``existing`` empty, emit no deletes,
        and silently turn a replace or a removal into an additive merge — while
        still reporting success.
        """
        existing = {e.id for e in self.load_ontology(refresh=True, strict=True).entities}
        keep = {e.id for e in ontology.entities}
        actions: list[dict] = [
            {"@search.action": "delete", "id": entity_id} for entity_id in existing - keep
        ]
        actions += [
            {"@search.action": "mergeOrUpload", **e.to_dict()} for e in ontology.entities
        ]
        if actions:
            self._post(ONTOLOGY_INDEX, "/docs/search.index", {"value": actions})
        self._ontology = ontology
        return len(ontology.entities)

    # -- REST plumbing ---------------------------------------------------------

    def _url(self, index: str, suffix: str) -> str:
        return f"{self._endpoint}/indexes('{index}'){suffix}?api-version={SEARCH_API_VERSION}"

    def _post(self, index: str, suffix: str, body: dict) -> dict | None:
        """POST to an index, creating the project's indexes on first
        'index not found' (a brand-new project) and retrying once. Requires
        Search Service Contributor — the Functions MI and seeded developers
        have it, so new projects need no manual `tacit provision`."""
        operation = lambda: request_json(  # noqa: E731
            method="POST",
            url=self._url(index, suffix),
            headers=search_headers(self._credential),
            body=body,
        )
        try:
            return operation()
        except RuntimeError as exc:
            if self._provisioned or "HTTP 404" not in str(exc):
                raise
            from .search_index import provision

            provision(self._settings, self._credential)
            self._provisioned = True
            return operation()

    # -- MemoryStore protocol ---------------------------------------------------

    def get(self, path: str) -> Memory | None:
        from urllib.error import HTTPError

        url = (
            f"{self._endpoint}/indexes('{self._memories_index}')"
            f"/docs('{quote(doc_key(self._project, path), safe='')}')"
            f"?api-version={SEARCH_API_VERSION}"
        )
        try:
            doc = request_json(method="GET", url=url, headers=search_headers(self._credential))
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
        except HTTPError:  # pragma: no cover - defensive
            return None
        return _memory_from_doc(doc) if doc else None

    def put(self, memory: Memory, version: MemoryVersion) -> None:
        self._post(
            self._memories_index,
            "/docs/search.index",
            {"value": [{"@search.action": "mergeOrUpload", **_memory_doc(memory)}]},
        )
        self._post(
            self._versions_index,
            "/docs/search.index",
            {"value": [{"@search.action": "upload", **_version_doc(version)}]},
        )
        self._sync_chunks(memory)

    def _sync_chunks(self, memory: Memory) -> None:
        """Re-project one memory into the chunks index: drop the sections it had,
        upload the ones it has now. A tombstoned memory keeps none, so deleted
        content can never surface in a search."""
        actions: list[dict] = [
            {"@search.action": "delete", "key": key} for key in self._chunk_keys(memory.path)
        ]
        if memory.status is MemoryStatus.ACTIVE:
            ontology = self.load_ontology()
            live = {
                chunk_key(memory.project, memory.path, s.slug): s
                for s in split_sections(memory.content)
            }
            actions = [a for a in actions if a["key"] not in live]
            docs = [
                _chunk_doc(memory, key, section, ontology) for key, section in live.items()
            ]
            for doc, vector in zip(docs, self._embed_sections(memory, list(live.values()))):
                # Omitted rather than sent empty: the field is declared with a
                # fixed dimension, so [] is rejected outright.
                if vector:
                    doc[VECTOR_FIELD] = vector
            actions += [{"@search.action": "mergeOrUpload", **doc} for doc in docs]
        if actions:
            self._post(self._chunks_index, "/docs/search.index", {"value": actions})

    def _embed_sections(self, memory: Memory, sections: list[Section]) -> list[list[float]]:
        """One vector per section, or nothing when vectors are off.

        The title is prepended to each section because sections are retrieved
        independently: "## Draining" carries no clue that it is about the
        payments gateway unless the memory's title travels with it.

        This is the only place embeddings are computed. Queries are embedded by
        the search service, but documents are pushed rather than crawled by an
        indexer, so their vectors can only come from the writer.
        """
        if self._embedder is None or not sections:
            return [[] for _ in sections]
        inputs = [f"{memory.title}\n\n{s.heading}\n{s.text}".strip() for s in sections]
        return self._embedder.embed(inputs)

    def visible_memories(self, scope: SearchScope | str | None = None) -> list[Memory]:
        """Every active memory the viewer may see, across projects.

        Search was previously the only operation that crossed a project
        boundary. The graph needs the same reach, and must obey exactly the
        same rules — so it shares ``scope_filter`` rather than re-deriving them.
        Paged, because a single response returns at most 1,000 rows and an
        organization-wide query is precisely the case that exceeds it.
        """
        resolved = parse_scope(scope)
        scoped = scope_filter(resolved, self._project, self._team, viewer=self._viewer)
        memories: list[Memory] = []
        skip = 0
        page = 1000
        while True:
            result = self._post(
                self._memories_index,
                "/docs/search.post.search",
                {
                    "search": "*",
                    "filter": f"status eq 'active' and {scoped}",
                    "orderby": "project asc, path asc",
                    "top": page,
                    "skip": skip,
                },
            )
            batch = (result or {}).get("value", [])
            memories.extend(_memory_from_doc(d) for d in batch)
            if len(batch) < page:
                return memories
            skip += page

    def reindex(self) -> int:
        """Rebuild the chunks index from the memories index, which is the system
        of record. Needed once for projects provisioned before sections existed,
        and safe to re-run — chunk keys are deterministic."""
        memories = self.list("/")
        for memory in memories:
            self._sync_chunks(memory)
        return len(memories)

    def _chunk_keys(self, path: str) -> list[str]:
        result = self._post(
            self._chunks_index,
            "/docs/search.post.search",
            {
                "search": "*",
                "filter": f"{self._own()} and path eq '{odata_quote(path)}'",
                "select": "key",
                "top": 1000,
            },
        )
        return [d["key"] for d in (result or {}).get("value", [])]

    def list(self, prefix: str = "/") -> list[Memory]:
        """Every active memory in this project, paged past the 1,000-row cap.

        A single request returns at most 1,000 documents while a project may
        hold up to the service cap, so a naive call would silently truncate —
        and `reindex` builds the chunks index from this, meaning the untouched
        remainder would exist but be unsearchable.
        """
        memories: list[Memory] = []
        skip = 0
        page = 1000
        while True:
            result = self._post(
                self._memories_index,
                "/docs/search.post.search",
                {
                    "search": "*",
                    "filter": f"status eq 'active' and {self._own()}",
                    "orderby": "path asc",
                    "top": page,
                    "skip": skip,
                },
            )
            batch = (result or {}).get("value", [])
            memories.extend(_memory_from_doc(d) for d in batch)
            if len(batch) < page:
                break
            skip += page
        return [m for m in memories if m.path.startswith(prefix)]

    def search(
        self,
        query: str,
        *,
        top: int = 5,
        category: str = "",
        scope: SearchScope | str | None = None,
        entity: str = "",
    ) -> list[SearchHit]:
        """Rank sections across every project the caller may see.

        The scope filter is what makes this organizational rather than
        per-team: one request reaches this project's memories and whatever the
        rest of the org has published, and the two are ranked together. Results
        are over-fetched, because the home-project boost and the one-hit-per-
        memory rule both reorder and thin the service's ranking — trimming to
        ``top`` before either would drop rows that should have survived.

        ``entity`` restricts to chunks annotated with a canonical entity id,
        which is the precise form of "everything the org knows about X"
        regardless of what each team calls it.

        The semantic ranker supplies the caption; when it is unavailable the
        BM25 highlight, then a locally computed extract, stand in — so a hit
        always costs a snippet rather than an entire memory.
        """
        resolved = parse_scope(scope)
        filters = [scope_filter(resolved, self._project, self._team, viewer=self._viewer)]
        if category:
            filters.append(f"category eq '{odata_quote(category)}'")
        if entity:
            filters.append(f"entities/any(e: e eq '{odata_quote(entity)}')")
        body: dict[str, Any] = {
            "search": query,
            "searchFields": SEARCH_FIELDS,
            "select": HIT_FIELDS,
            "highlight": "content",
            "highlightPreTag": "",
            "highlightPostTag": "",
            "scoringProfile": SCORING_PROFILE,
            "filter": " and ".join(filters),
            "top": _overfetch(top),
        }
        vector_query = self._vector_query(query)
        if vector_query:
            body["vectorQueries"] = [vector_query]
        result = self._search_ranked(body)
        scored: list[tuple[float, SearchHit]] = []
        for doc in (result or {}).get("value", []):
            text, truncated = narrow(doc.get("content") or "", _extract_from(doc, query))
            project = doc.get("project") or ""
            raw = float(doc.get("@search.rerankerScore") or doc.get("@search.score") or 0.0)
            hit = SearchHit(
                path=doc["path"],
                title=doc.get("title") or doc["path"],
                category=doc.get("category") or "general",
                project=project or self._project,
                team=doc.get("team") or "",
                tags=doc.get("tags") or [],
                score=raw,
                section=doc.get("section") or "",
                heading=doc.get("heading") or "",
                content=text,
                truncated=truncated,
            )
            boosted = raw * (HOME_PROJECT_BOOST if project == self._project else 1.0)
            scored.append((boosted, hit))
        return _best_per_memory(scored, top)

    def _vector_query(self, query: str) -> dict | None:
        """The vector half of a hybrid query, or None when vectors are off.

        The query travels as plain text: the index's vectorizer embeds it, so
        no model call happens in this process and only the search service needs
        access to the deployment.

        ``k`` is the reranker window rather than ``top``. Azure fuses the BM25
        and vector candidate lists with RRF and hands at most 50 rows to the
        semantic ranker, so a smaller ``k`` starves the stage that decides the
        final order.
        """
        if not self._vectors:
            return None
        return {
            "kind": "text",
            "text": query,
            "fields": VECTOR_FIELD,
            "k": SEMANTIC_RERANK_WINDOW,
        }

    def _search_ranked(self, body: dict) -> dict | None:
        """Hybrid candidates, semantically reranked.

        No capability probing: `tacit provision` creates this index with the
        semantic configuration and the vector profile, so both are present by
        construction. If either is missing the query fails loudly, which says
        "run provision" instead of quietly halving recall.
        """
        semantic = {
            **body,
            "queryType": "semantic",
            "semanticConfiguration": SEMANTIC_CONFIG,
            "captions": "extractive|highlight-false",
        }
        # The L2 reranker orders the fused set; a scoring profile would only
        # shape BM25 candidates it never sees.
        semantic.pop("scoringProfile", None)
        return self._post(self._chunks_index, "/docs/search.post.search", semantic)

    def versions(self, path: str) -> list[MemoryVersion]:
        result = self._post(
            self._versions_index,
            "/docs/search.post.search",
            {
                "search": "*",
                "filter": f"{self._own()} and path eq '{odata_quote(path)}'",
                "orderby": "version asc",
                "top": 1000,
            },
        )
        return [_version_from_doc(d) for d in (result or {}).get("value", [])]

    def count(self) -> int:
        result = self._post(
            self._memories_index,
            "/docs/search.post.search",
            {
                "search": "*",
                "filter": f"status eq 'active' and {self._own()}",
                "top": 0,
                "count": True,
            },
        )
        return int((result or {}).get("@odata.count") or 0)


def _overfetch(top: int) -> int:
    """How many chunks to ask the service for to return ``top`` memories.

    Several sections of one memory can match, and only the best is kept, so
    asking for exactly ``top`` would routinely return fewer. Capped at 50
    because that is the semantic reranker's window: rows beyond it come back
    without ``@search.rerankerScore`` and would fall back to raw BM25, which is
    on a different, unbounded scale — sorting the two together lets an
    unreranked tail outrank the reranked head.
    """
    return max(min(top * 4, SEMANTIC_RERANK_WINDOW), min(top, SEMANTIC_RERANK_WINDOW))


def _best_per_memory(scored: list[tuple[float, SearchHit]], top: int) -> list[SearchHit]:
    """One hit per memory, best section first — the local backend's contract.

    Sorting is by the boosted score but the hit keeps its raw one, so callers
    compare like with like across projects and the home bias stays an internal
    ranking decision rather than a number an agent might reason about.
    """
    ordered = sorted(scored, key=lambda pair: -pair[0])
    hits: list[SearchHit] = []
    seen: set[tuple[str, str]] = set()
    for _boosted, hit in ordered:
        identity = (hit.project, hit.path)
        if identity in seen:
            continue
        seen.add(identity)
        hits.append(hit)
        if len(hits) >= top:
            break
    return hits


def _extract_from(doc: dict, query: str) -> str:
    """The best short stand-in for a long section: the semantic ranker's
    caption, else its BM25 highlights, else a locally computed extract.
    Whether the stand-in is actually used is ``narrow``'s decision."""
    content = " ".join((doc.get("content") or "").split())
    captions = doc.get("@search.captions") or []
    if captions:
        caption = " ".join((captions[0].get("text") or "").split())
        if caption:
            return caption
    highlights = (doc.get("@search.highlights") or {}).get("content") or []
    if highlights:
        return " … ".join(" ".join(h.split()) for h in highlights[:2])
    return snippet(content, query)


def _strip_metadata(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if not k.startswith("@search.")}


def _chunk_doc(
    memory: Memory, key: str, section: Section, ontology: Ontology | None = None
) -> dict:
    # Annotate against title + heading + body: an entity named only in the
    # memory's title still governs every section beneath it.
    ontology = ontology or Ontology()
    entities = ontology.annotate(f"{memory.title}\n{section.heading}\n{section.text}")
    return {
        "key": key,
        "path": memory.path,
        "project": memory.project,
        "team": memory.team,
        "visibility": str(memory.visibility),
        "section": section.slug,
        "heading": section.heading,
        "title": memory.title,
        "content": section.text,
        "category": memory.category,
        "tags": list(memory.tags),
        "entities": entities,
        "entity_vocabulary": ontology.vocabulary_for(entities),
        "updated": memory.updated.isoformat(),
    }


def _memory_doc(memory: Memory) -> dict:
    return {
        "key": memory.key,
        "path": memory.path,
        "project": memory.project,
        "team": memory.team,
        "visibility": str(memory.visibility),
        "title": memory.title,
        "content": memory.content,
        "category": memory.category,
        "tags": list(memory.tags),
        "version": memory.version,
        "content_sha256": memory.content_sha256,
        "status": str(memory.status),
        "created_by": memory.created_by,
        "updated_by": memory.updated_by,
        "created": memory.created.isoformat(),
        "updated": memory.updated.isoformat(),
    }


def _memory_from_doc(doc: dict) -> Memory:
    return Memory(
        path=doc["path"],
        content=doc.get("content") or "",
        project=doc.get("project") or DEFAULT_PROJECT,
        team=doc.get("team") or "",
        visibility=Visibility(doc.get("visibility") or Visibility.ORG),
        category=doc.get("category") or "general",
        tags=doc.get("tags") or [],
        version=int(doc.get("version") or 1),
        content_sha256=doc.get("content_sha256") or "",
        status=MemoryStatus(doc.get("status") or "active"),
        created_by=doc.get("created_by") or "unknown",
        updated_by=doc.get("updated_by") or "unknown",
        created=doc.get("created"),
        updated=doc.get("updated"),
    )


def _version_doc(version: MemoryVersion) -> dict:
    return {
        "key": version.key,
        "path": version.path,
        "project": version.project,
        "version": version.version,
        "operation": version.operation,
        "content": version.content,
        "content_sha256": version.content_sha256,
        "actor": version.actor,
        "timestamp": version.timestamp.isoformat(),
    }


def _version_from_doc(doc: dict) -> MemoryVersion:
    return MemoryVersion(
        path=doc["path"],
        project=doc.get("project") or DEFAULT_PROJECT,
        version=int(doc["version"]),
        operation=doc.get("operation") or "update",
        content=doc.get("content") or "",
        content_sha256=doc.get("content_sha256") or "",
        actor=doc.get("actor") or "unknown",
        timestamp=doc.get("timestamp"),
    )
