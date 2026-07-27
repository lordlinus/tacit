"""File-backed store: one JSON file for latest state, one JSONL for versions.

This is the hermetic backend — tests, the benchmark, and offline dev all run
against it. Search is a small TF-IDF ranker over the same section chunks the
AI Search backend indexes, with the same title/tag weighting, so relevance
ordering behaves like the cloud without the cloud.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from .models import Memory, MemoryStatus, MemoryVersion, SearchHit
from .sections import Section, narrow, snippet, split_sections

_WORD = re.compile(r"[a-z0-9]+")

TITLE_WEIGHT = 3
TAG_WEIGHT = 2


def _terms(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class LocalStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._memories_path = self.root / "memories.json"
        self._versions_path = self.root / "versions.jsonl"
        self._memories: dict[str, Memory] = {}
        self._load()

    def _load(self) -> None:
        if self._memories_path.exists():
            raw = json.loads(self._memories_path.read_text(encoding="utf-8"))
            self._memories = {p: Memory.model_validate(m) for p, m in raw.items()}

    def _flush(self) -> None:
        raw = {p: m.model_dump(mode="json") for p, m in self._memories.items()}
        self._memories_path.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # -- MemoryStore protocol -------------------------------------------------

    def get(self, path: str) -> Memory | None:
        return self._memories.get(path)

    def put(self, memory: Memory, version: MemoryVersion) -> None:
        self._memories[memory.path] = memory
        self._flush()
        with self._versions_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(version.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def list(self, prefix: str = "/") -> list[Memory]:
        return sorted(
            (
                m
                for m in self._memories.values()
                if m.status is MemoryStatus.ACTIVE and m.path.startswith(prefix)
            ),
            key=lambda m: m.path,
        )

    def reindex(self) -> int:
        """No-op: the local backend sections at query time, so it has no derived
        index to rebuild. Present so callers need not special-case the backend."""
        return len(self.list("/"))

    def search(self, query: str, *, top: int = 5, category: str = "") -> list[SearchHit]:
        """Rank sections, not whole memories, and return a snippet of each."""
        chunks: list[tuple[Memory, Section]] = [
            (m, section)
            for m in self._memories.values()
            if m.status is MemoryStatus.ACTIVE and (not category or m.category == category)
            for section in split_sections(m.content)
        ]
        if not chunks:
            return []
        query_terms = _terms(query)
        n_docs = len(chunks)
        doc_freq: Counter[str] = Counter()
        chunk_terms: list[Counter[str]] = []
        for memory, section in chunks:
            # Title and tags get repeated so matches there outrank body matches
            # — the same bias the AI Search scoring profile applies.
            weighted = (
                _terms(memory.title) * TITLE_WEIGHT
                + _terms(" ".join(memory.tags)) * TAG_WEIGHT
                + _terms(section.heading)
                + _terms(section.text)
            )
            counts = Counter(weighted)
            chunk_terms.append(counts)
            for term in counts:
                doc_freq[term] += 1

        scored: list[tuple[float, Memory, Section]] = []
        for (memory, section), counts in zip(chunks, chunk_terms, strict=True):
            score = sum(
                (1 + math.log(counts[t])) * math.log(1 + n_docs / doc_freq[t])
                for t in query_terms
                if counts.get(t)
            )
            if score > 0:
                scored.append((score, memory, section))
        scored.sort(key=lambda triple: (-triple[0], triple[1].path, triple[2].slug))

        hits: list[SearchHit] = []
        seen: set[str] = set()
        for score, memory, section in scored:
            # One hit per memory: the best-scoring section represents it.
            if memory.path in seen:
                continue
            seen.add(memory.path)
            text, truncated = narrow(section.text, snippet(section.text, query))
            hits.append(
                SearchHit(
                    path=memory.path,
                    title=memory.title,
                    category=memory.category,
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
                if record["path"] == path:
                    out.append(MemoryVersion.model_validate(record))
        return sorted(out, key=lambda v: v.version)

    def count(self) -> int:
        return sum(1 for m in self._memories.values() if m.status is MemoryStatus.ACTIVE)
