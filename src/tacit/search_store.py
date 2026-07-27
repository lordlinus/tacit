"""Azure AI Search backend — same MemoryStore protocol as LocalStore.

Latest state is mergeOrUpload-ed into ``tm-<project>`` (key = path slug);
every mutation also uploads an immutable doc to ``tm-<project>-versions``
(key = path slug + version) and re-projects the memory's sections into
``tm-<project>-chunks``, the index searches run against.

Search asks for the semantic ranker (L2 reranking + extractive captions) and
falls back to plain BM25 when the service declines — semantic is a capacity
feature, so a store must stay usable without it.

Note: AI Search indexing is near-real-time, not transactional — a doc becomes
searchable within seconds of upload. ``get`` uses the lookup API (consistent),
so the concurrency contract (sha preconditions) is not affected by search lag.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .azure_common import SEARCH_API_VERSION, build_credential, request_json, search_headers
from .config import Settings
from .models import Memory, MemoryStatus, MemoryVersion, SearchHit, path_key
from .search_index import SCORING_PROFILE, SEMANTIC_CONFIG, index_names
from .sections import Section, narrow, snippet, split_sections

SEARCH_FIELDS = "title,tags,heading,content"
HIT_FIELDS = "path,section,heading,title,category,tags,content"


def odata_quote(value: str) -> str:
    """Escape a string literal for an OData filter (single quotes double up)."""
    return value.replace("'", "''")


def chunk_key(path: str, section: str) -> str:
    return f"{path_key(path)}--s-{section}"


class SearchStore:
    def __init__(self, settings: Settings, credential: Any | None = None) -> None:
        self._settings = settings
        self._endpoint = settings.search_endpoint.rstrip("/")
        self._credential = credential or build_credential(settings.auth_mode, settings.tenant_id)
        self._memories_index, self._versions_index, self._chunks_index = index_names(
            settings.project
        )
        self._provisioned = False
        self._semantic_ok = True

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
            f"/docs('{quote(path_key(path), safe='')}')?api-version={SEARCH_API_VERSION}"
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
            live = {
                chunk_key(memory.path, s.slug): s for s in split_sections(memory.content)
            }
            actions = [a for a in actions if a["key"] not in live]
            actions += [
                {"@search.action": "mergeOrUpload", **_chunk_doc(memory, key, section)}
                for key, section in live.items()
            ]
        if actions:
            self._post(self._chunks_index, "/docs/search.index", {"value": actions})

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
                "filter": f"path eq '{odata_quote(path)}'",
                "select": "key",
                "top": 1000,
            },
        )
        return [d["key"] for d in (result or {}).get("value", [])]

    def list(self, prefix: str = "/") -> list[Memory]:
        result = self._post(
            self._memories_index,
            "/docs/search.post.search",
            {
                "search": "*",
                "filter": "status eq 'active'",
                "orderby": "path asc",
                "top": 1000,
            },
        )
        memories = [_memory_from_doc(d) for d in (result or {}).get("value", [])]
        return [m for m in memories if m.path.startswith(prefix)]

    def search(self, query: str, *, top: int = 5, category: str = "") -> list[SearchHit]:
        """Rank sections, not whole memories, and return a snippet of each.

        The semantic ranker supplies the caption; when it is unavailable the
        BM25 highlight, then a locally computed extract, stand in — so a hit
        always costs a snippet rather than an entire memory.
        """
        filters = ""
        if category:
            filters = f"category eq '{odata_quote(category)}'"
        body: dict[str, Any] = {
            "search": query,
            "searchFields": SEARCH_FIELDS,
            "select": HIT_FIELDS,
            "highlight": "content",
            "highlightPreTag": "",
            "highlightPostTag": "",
            "scoringProfile": SCORING_PROFILE,
            "top": top,
        }
        if filters:
            body["filter"] = filters
        result = self._search_ranked(body)
        hits = []
        for doc in (result or {}).get("value", []):
            text, truncated = narrow(doc.get("content") or "", _extract_from(doc, query))
            hits.append(
                SearchHit(
                    path=doc["path"],
                    title=doc.get("title") or doc["path"],
                    category=doc.get("category") or "general",
                    tags=doc.get("tags") or [],
                    score=float(
                        doc.get("@search.rerankerScore") or doc.get("@search.score") or 0.0
                    ),
                    section=doc.get("section") or "",
                    heading=doc.get("heading") or "",
                    content=text,
                    truncated=truncated,
                )
            )
        return hits

    def _search_ranked(self, body: dict) -> dict | None:
        """Semantic first, BM25 if the service declines it. The downgrade is
        sticky: one rejection means this store has no semantic capacity."""
        if self._semantic_ok:
            semantic = {
                **body,
                "queryType": "semantic",
                "semanticConfiguration": SEMANTIC_CONFIG,
                "captions": "extractive|highlight-false",
            }
            # A semantic query is reranked by the L2 model; a scoring profile
            # only shapes the BM25 candidates it never sees.
            semantic.pop("scoringProfile", None)
            try:
                return self._post(
                    self._chunks_index, "/docs/search.post.search", semantic
                )
            except RuntimeError as exc:
                if not _is_semantic_rejection(exc):
                    raise
                self._semantic_ok = False
        return self._post(self._chunks_index, "/docs/search.post.search", body)

    def versions(self, path: str) -> list[MemoryVersion]:
        result = self._post(
            self._versions_index,
            "/docs/search.post.search",
            {
                "search": "*",
                "filter": f"path eq '{odata_quote(path)}'",
                "orderby": "version asc",
                "top": 1000,
            },
        )
        return [_version_from_doc(d) for d in (result or {}).get("value", [])]

    def count(self) -> int:
        result = self._post(
            self._memories_index,
            "/docs/search.post.search",
            {"search": "*", "filter": "status eq 'active'", "top": 0, "count": True},
        )
        return int((result or {}).get("@odata.count") or 0)


def _is_semantic_rejection(exc: Exception) -> bool:
    """Distinguish 'this service/tier cannot do semantic' from a real failure."""
    text = str(exc).lower()
    return "semantic" in text and ("400" in text or "403" in text or "not enabled" in text)


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


def _chunk_doc(memory: Memory, key: str, section: Section) -> dict:
    return {
        "key": key,
        "path": memory.path,
        "section": section.slug,
        "heading": section.heading,
        "title": memory.title,
        "content": section.text,
        "category": memory.category,
        "tags": list(memory.tags),
        "updated": memory.updated.isoformat(),
    }


def _memory_doc(memory: Memory) -> dict:
    return {
        "key": memory.key,
        "path": memory.path,
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
        "key": f"{path_key(version.path)}-v{version.version}",
        "path": version.path,
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
        version=int(doc["version"]),
        operation=doc.get("operation") or "update",
        content=doc.get("content") or "",
        content_sha256=doc.get("content_sha256") or "",
        actor=doc.get("actor") or "unknown",
        timestamp=doc.get("timestamp"),
    )
