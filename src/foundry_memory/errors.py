"""Structured errors. Sha conflicts carry everything an agent needs to
re-read and retry deliberately instead of failing opaquely."""

from __future__ import annotations


class MemoryError_(Exception):
    """Base class (trailing underscore: ``MemoryError`` is a builtin)."""


class MemoryNotFoundError(MemoryError_):
    def __init__(self, path: str, *, tombstoned: bool = False) -> None:
        self.path = path
        self.tombstoned = tombstoned
        suffix = " (tombstoned)" if tombstoned else ""
        super().__init__(f"no memory at {path!r}{suffix}")


class DuplicatePathError(MemoryError_):
    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"memory already exists at {path!r}; use memory_update")


class ShaConflictError(MemoryError_):
    def __init__(self, path: str, *, expected: str, current: str, current_version: int) -> None:
        self.path = path
        self.expected = expected
        self.current = current
        self.current_version = current_version
        super().__init__(
            f"sha conflict on {path!r}: expected {expected[:12]}, "
            f"current {current[:12]} (v{current_version}). Re-read and retry."
        )

    def as_result(self) -> dict:
        """Structured MCP tool result, mirroring PEMP's conflict contract."""
        return {
            "error": "sha_conflict",
            "path": self.path,
            "expected_sha256": self.expected,
            "current_sha256": self.current,
            "current_version": self.current_version,
            "hint": "Re-read the memory with memory_read and retry with the current sha.",
        }


class StoreFullError(MemoryError_):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(
            f"store is at its {limit}-memory cap; prune with memory_delete or run a dream"
        )
