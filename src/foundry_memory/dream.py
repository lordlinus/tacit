"""Dream: curate a memory store into a new one (Anthropic Dreams, mini edition).

Inputs: an existing store + past session transcripts. Output: a **new** store —
duplicates merged, stale entries superseded by the newest version of the fact,
and fresh insights mined from the transcripts. The input store is never
modified, so the result can be reviewed and discarded.

The default consolidator is deterministic (string similarity + marker mining)
so the pipeline is hermetic and unit-testable; ``Consolidator`` is a protocol,
and an LLM-backed implementation can be swapped in for semantic-quality merges.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .models import Memory
from .service import MemoryService

# Lines agents drop into transcripts when they learn something durable.
_INSIGHT_MARKERS = re.compile(r"^\s*(?:LEARNED|GOTCHA|CONVENTION|DECISION):\s*(.+)$", re.MULTILINE)
_SIMILARITY_THRESHOLD = 0.72


@dataclass
class DreamReport:
    kept: int = 0
    merged: int = 0  # memories folded into another (duplicates removed)
    superseded: int = 0  # older contradicted versions replaced
    mined: int = 0  # new insights extracted from transcripts
    notes: list[str] = field(default_factory=list)


class Consolidator(Protocol):
    def merge_group(self, group: list[Memory]) -> Memory:
        """Collapse near-duplicate memories into one survivor."""
        ...


class HeuristicConsolidator:
    """Newest content wins; tags union; provenance noted in the body."""

    def merge_group(self, group: list[Memory]) -> Memory:
        newest = max(group, key=lambda m: m.updated)
        if len(group) == 1:
            return newest
        tags = sorted({t for m in group for t in m.tags})
        others = sorted(m.path for m in group if m.path != newest.path)
        content = newest.content.rstrip("\n")
        content += f"\n\n<!-- dream: merged {', '.join(others)} -->\n"
        return newest.model_copy(update={"tags": tags, "content": content})


def _normalized_title(memory: Memory) -> str:
    return re.sub(r"[^a-z0-9 ]", "", memory.title.lower()).strip()


def _group_duplicates(memories: list[Memory]) -> list[list[Memory]]:
    """Cluster by normalized-title similarity (transitive, greedy)."""
    groups: list[list[Memory]] = []
    for memory in sorted(memories, key=lambda m: m.path):
        title = _normalized_title(memory)
        placed = False
        for group in groups:
            if any(
                difflib.SequenceMatcher(None, title, _normalized_title(m)).ratio()
                >= _SIMILARITY_THRESHOLD
                for m in group
            ):
                group.append(memory)
                placed = True
                break
        if not placed:
            groups.append([memory])
    return groups


def _mine_transcript(text: str) -> list[str]:
    return [m.strip() for m in _INSIGHT_MARKERS.findall(text) if m.strip()]


def _insight_path(insight: str, taken: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", insight.lower()).strip("-")[:60].strip("-") or "insight"
    path = f"/dreamed/{slug}.md"
    n = 2
    while path in taken:
        path = f"/dreamed/{slug}-{n}.md"
        n += 1
    return path


def _covered(insight: str, memories: list[Memory]) -> bool:
    """Is this insight already expressed by an existing memory?"""
    needle = _normalized_title_text(insight)
    for memory in memories:
        haystack = _normalized_title_text(memory.title + " " + memory.content)
        if needle and needle in haystack:
            return True
        if difflib.SequenceMatcher(None, needle, _normalized_title_text(memory.title)).ratio() >= _SIMILARITY_THRESHOLD:
            return True
    return False


def _normalized_title_text(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def dream(
    input_service: MemoryService,
    output_service: MemoryService,
    *,
    transcripts: list[str] | None = None,
    consolidator: Consolidator | None = None,
) -> DreamReport:
    """Read everything from the input store, write the curated result to the
    output store. The output store must be empty (a fresh dream, not a merge)."""
    if output_service.list("/"):
        raise ValueError("dream output store must be empty; point at a fresh store")
    consolidator = consolidator or HeuristicConsolidator()
    report = DreamReport()

    memories = input_service.list("/")
    survivors: list[Memory] = []
    for group in _group_duplicates(memories):
        survivor = consolidator.merge_group(group)
        survivors.append(survivor)
        report.kept += 1
        if len(group) > 1:
            report.merged += len(group) - 1
            report.superseded += sum(
                1 for m in group if m.path != survivor.path and m.updated < survivor.updated
            )
            report.notes.append(
                f"merged {len(group)} memories into {survivor.path}"
            )

    for memory in survivors:
        output_service.create(
            memory.path, memory.content, category=memory.category, tags=memory.tags
        )

    taken = {m.path for m in survivors}
    for transcript in transcripts or []:
        for insight in _mine_transcript(transcript):
            if _covered(insight, survivors):
                continue
            path = _insight_path(insight, taken)
            taken.add(path)
            output_service.create(
                path,
                f"# {insight}\n\n(Surfaced by a dream from a past session transcript.)\n",
                category="gotcha",
                tags=["dreamed"],
            )
            report.mined += 1
            report.notes.append(f"mined insight -> {path}")

    return report


def load_transcripts(directory: Path) -> list[str]:
    """Read session transcripts: .txt/.md as-is; .jsonl as message-content lines."""
    texts = []
    for file in sorted(directory.glob("*")):
        if file.suffix in {".txt", ".md"}:
            texts.append(file.read_text(encoding="utf-8"))
        elif file.suffix == ".jsonl":
            lines = []
            for line in file.read_text(encoding="utf-8").splitlines():
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    lines.append(content)
            texts.append("\n".join(lines))
    return texts
