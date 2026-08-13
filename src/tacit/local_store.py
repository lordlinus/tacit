"""File-backed store: one JSON file for latest state, one JSONL for versions.

This is the hermetic backend — tests, the benchmark, and offline dev all run
against it. Like the Azure backend it is **organization-wide**: one root holds
every project's memories, keyed by ``(project, path)``, and each instance is a
project-scoped view onto that shared file. That parity is the point — a
cross-team search can be tested without touching Azure, and a scoping bug
shows up in the hermetic suite rather than in production.

Search is a small TF-IDF ranker over the same section chunks the AI Search
backend indexes, with the same title/tag weighting and the same home-project
boost, so relevance ordering behaves like the cloud without the cloud.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from .models import (
    DEFAULT_PROJECT,
    HOME_PROJECT_BOOST,
    Memory,
    MemoryStatus,
    MemoryVersion,
    SearchHit,
    SearchScope,
)
from .ontology import Ontology
from .scope import Viewer, parse_scope, permits
from .sections import Section, narrow, snippet, split_sections
_WORD = re.compile(r"[a-z0-9]+")

TITLE_WEIGHT = 3
TAG_WEIGHT = 2


def _terms(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class LocalStore:
    def __init__(
        self,
        root: Path | str,
        *,
        project: str = DEFAULT_PROJECT,
        team: str = "",
        viewer: "Viewer | None" = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.project = project
        self.team = team
        self._viewer = viewer or Viewer(project=project, team=team)
        self._memories_path = self.root / "memories.json"
        self._versions_path = self.root / "versions.jsonl"
        self._ontology_path = self.root / "ontology.json"
        self._memories: dict[tuple[str, str], Memory] = {}
        self._loaded_stamp: tuple[int, int] | None = None
        self._load()

    # -- vocabulary ------------------------------------------------------------

    def load_ontology(self, *, refresh: bool = False, strict: bool = False) -> Ontology:
        """The organization's controlled vocabulary (shared across projects).

        Read from disk every time rather than cached: several project-scoped
        stores share one file in this process, and a stale vocabulary would
        make cross-team matching silently depend on which store loaded first.
        The file is small and this backend is for tests and offline dev, so the
        read is not worth optimising. ``refresh``/``strict`` exist for protocol
        parity with the Azure backend, which caches and can fail to reach it.
        """
        return Ontology.load(self._ontology_path)

    def save_ontology(self, ontology: Ontology) -> int:
        """Replace the vocabulary; returns the number of entities stored."""
        ontology.save(self._ontology_path)
        return len(ontology.entities)

    # -- persistence -----------------------------------------------------------

    def _stamp(self) -> tuple[int, int] | None:
        try:
            stat = self._memories_path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _load(self) -> None:
        """(Re)read the shared file when another project's store has written it.

        One process holds a store per project over the same file, so a cached
        view would make one project's writes invisible to another's search —
        exactly the cross-team case this backend exists to test.
        """
        stamp = self._stamp()
        if stamp == self._loaded_stamp and self._memories:
            return
        self._loaded_stamp = stamp
        if stamp is None:
            self._memories = {}
            return
        raw = json.loads(self._memories_path.read_text(encoding="utf-8"))
        memories = {}
        for record in raw.values():
            memory = Memory.model_validate(record)
            memories[(memory.project, memory.path)] = memory
        self._memories = memories

    def _flush(self) -> None:
        raw = {
            f"{project}|{path}": memory.model_dump(mode="json")
            for (project, path), memory in sorted(self._memories.items())
        }
        self._memories_path.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self._loaded_stamp = self._stamp()

    # -- MemoryStore protocol -------------------------------------------------

    def get(self, path: str) -> Memory | None:
        self._load()
        return self._memories.get((self.project, path))

    def put(self, memory: Memory, version: MemoryVersion) -> None:
        self._load()
        self._memories[(memory.project, memory.path)] = memory
        self._flush()
        with self._versions_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(version.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def list(self, prefix: str = "/") -> list[Memory]:
        self._load()
        return sorted(
            (
                m
                for m in self._memories.values()
                if m.project == self.project
                and m.status is MemoryStatus.ACTIVE
                and m.path.startswith(prefix)
            ),
            key=lambda m: m.path,
        )

    def visible_memories(self, scope: SearchScope | str | None = None) -> list[Memory]:
        """Every active memory the viewer may see, across projects.

        Search was previously the only operation that crossed a project
        boundary. The graph needs the same reach, and must obey exactly the
        same rules — so it shares ``permits`` rather than re-deriving them.
        """
        self._load()
        resolved = parse_scope(scope)
        return sorted(
            (
                m
                for m in self._memories.values()
                if m.status is MemoryStatus.ACTIVE
                and permits(m, resolved, self.project, self.team, viewer=self._viewer)
            ),
            key=lambda m: (m.project, m.path),
        )

    def reindex(self) -> int:
        """No-op: the local backend sections at query time, so it has no derived
        index to rebuild. Present so callers need not special-case the backend."""
        return len(self.list("/"))

    def search(
        self,
        query: str,
        *,
        top: int = 5,
        category: str = "",
        scope: SearchScope | str | None = None,
        entity: str = "",
    ) -> list[SearchHit]:
        """Rank sections across every project ``scope`` and visibility admit."""
        self._load()
        resolved = parse_scope(scope)
        ontology = self.load_ontology()
        visible = [
            m
            for m in self._memories.values()
            if m.status is MemoryStatus.ACTIVE
            and (not category or m.category == category)
            and permits(m, resolved, self.project, self.team, viewer=self._viewer)
        ]
        chunks: list[tuple[Memory, Section, list[str]]] = []
        for memory in visible:
            for section in split_sections(memory.content):
                entities = ontology.annotate(
                    f"{memory.title}\n{section.heading}\n{section.text}"
                )
                if entity and entity not in entities:
                    continue
                chunks.append((memory, section, entities))
        if not chunks:
            return []
        query_terms = _terms(query)
        n_docs = len(chunks)
        doc_freq: Counter[str] = Counter()
        chunk_terms: list[Counter[str]] = []
        for memory, section, entities in chunks:
            # Title and tags get repeated so matches there outrank body matches
            # — the same bias the AI Search scoring profile applies. The
            # entities' aliases are folded in unweighted, mirroring the
            # `entity_vocabulary` field on the cloud chunk: they widen which
            # phrasings match without inflating relevance on their own.
            weighted = (
                _terms(memory.title) * TITLE_WEIGHT
                + _terms(" ".join(memory.tags)) * TAG_WEIGHT
                + _terms(section.heading)
                + _terms(section.text)
                + _terms(ontology.vocabulary_for(entities))
            )
            counts = Counter(weighted)
            chunk_terms.append(counts)
            for term in counts:
                doc_freq[term] += 1

        scored: list[tuple[float, float, Memory, Section]] = []
        for (memory, section, _entities), counts in zip(chunks, chunk_terms, strict=True):
            score = sum(
                (1 + math.log(counts[t])) * math.log(1 + n_docs / doc_freq[t])
                for t in query_terms
                if counts.get(t)
            )
            if score > 0:
                boost = HOME_PROJECT_BOOST if memory.project == self.project else 1.0
                scored.append((score * boost, score, memory, section))
        # Sort by the boosted score, but report the raw one, so scores stay
        # comparable across projects and the home bias is not something an
        # agent has to reason about.
        scored.sort(key=lambda row: (-row[0], row[2].project, row[2].path, row[3].slug))

        hits: list[SearchHit] = []
        seen: set[tuple[str, str]] = set()
        for _boosted, score, memory, section in scored:
            # One hit per memory: the best-scoring section represents it.
            identity = (memory.project, memory.path)
            if identity in seen:
                continue
            seen.add(identity)
            text, truncated = narrow(section.text, snippet(section.text, query))
            hits.append(
                SearchHit(
                    path=memory.path,
                    title=memory.title,
                    category=memory.category,
                    project=memory.project,
                    team=memory.team,
                    tags=memory.tags,
                    score=round(score, 4),
                    section=section.slug,
                    heading=section.heading,
                    content=text,
                    truncated=truncated,
                )
            )
            if len(hits) >= top:
                break
        return hits

    def versions(self, path: str) -> list[MemoryVersion]:
        if not self._versions_path.exists():
            return []
        out = []
        with self._versions_path.open(encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                if record["path"] == path and record.get("project", DEFAULT_PROJECT) == self.project:
                    out.append(MemoryVersion.model_validate(record))
        return sorted(out, key=lambda v: v.version)

    def count(self) -> int:
        self._load()
        return sum(
            1
            for m in self._memories.values()
            if m.project == self.project and m.status is MemoryStatus.ACTIVE
        )

