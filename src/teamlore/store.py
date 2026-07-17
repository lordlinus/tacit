"""The storage protocol both backends implement.

Stores are dumb: they persist and query documents. Validation, optimistic
concurrency, tombstones, and version appending live in the service layer so
the two backends can't drift.
"""

from __future__ import annotations

from typing import Protocol

from .models import Memory, MemoryVersion, SearchHit


class MemoryStore(Protocol):
    def get(self, path: str) -> Memory | None:
        """Latest state of a memory, tombstones included; None if never written."""
        ...

    def put(self, memory: Memory, version: MemoryVersion) -> None:
        """Persist the latest state and append its version record atomically
        (as atomically as the backend allows)."""
        ...

    def list(self, prefix: str = "/") -> list[Memory]:
        """Active memories under a path prefix, sorted by path."""
        ...

    def search(self, query: str, *, top: int = 5, category: str = "") -> list[SearchHit]:
        """Ranked full-text search over active memories."""
        ...

    def versions(self, path: str) -> list[MemoryVersion]:
        """Audit trail for a path, oldest first."""
        ...

    def count(self) -> int:
        """Number of active memories (for the store cap)."""
        ...
