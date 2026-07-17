"""File-backed store: one JSON file for latest state, one JSONL for versions.

This is the hermetic backend — tests, the benchmark, and offline dev all run
against it. Search is a small TF-IDF ranker so relevance ordering behaves like
the AI Search backend (BM25) without the cloud.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from .models import Memory, MemoryStatus, MemoryVersion, SearchHit

_WORD = re.compile(r"[a-z0-9]+")


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

    def search(self, query: str, *, top: int = 5, category: str = "") -> list[SearchHit]:
        active = [
            m
            for m in self._memories.values()
            if m.status is MemoryStatus.ACTIVE and (not category or m.category == category)
        ]
        if not active:
            return []
        query_terms = _terms(query)
        n_docs = len(active)
        doc_freq: Counter[str] = Counter()
        doc_terms: dict[str, Counter[str]] = {}
        for m in active:
            # Title and tags get repeated so matches there outrank body matches.
            weighted = _terms(m.title) * 3 + _terms(" ".join(m.tags)) * 2 + _terms(m.content)
            counts = Counter(weighted)
            doc_terms[m.path] = counts
            for term in counts:
                doc_freq[term] += 1

        scored: list[tuple[float, Memory]] = []
        for m in active:
            counts = doc_terms[m.path]
            score = sum(
                (1 + math.log(counts[t])) * math.log(1 + n_docs / doc_freq[t])
                for t in query_terms
                if counts.get(t)
            )
            if score > 0:
                scored.append((score, m))
        scored.sort(key=lambda pair: (-pair[0], pair[1].path))
        return [
            SearchHit(
                path=m.path,
                title=m.title,
                category=m.category,
                tags=m.tags,
                score=round(score, 4),
                content=m.content,
            )
            for score, m in scored[:top]
        ]

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
