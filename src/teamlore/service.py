"""The memory service: every mutation goes through here.

Enforces the platform invariants over any MemoryStore backend:
immutable versions, sha-preconditioned mutations, tombstone deletes,
and the store cap. Reads are pass-throughs.
"""

from __future__ import annotations

from collections.abc import Sequence

from .errors import DuplicatePathError, MemoryNotFoundError, ShaConflictError, StoreFullError
from .models import (
    Memory,
    MemoryStatus,
    MemoryVersion,
    SearchHit,
    canonical_content,
    content_sha256,
    utcnow,
    validate_path,
)
from .store import MemoryStore

DEFAULT_STORE_CAP = 2000
BRIEF_CATEGORY = "onboarding"


class MemoryService:
    def __init__(self, store: MemoryStore, *, actor: str = "unknown", cap: int = DEFAULT_STORE_CAP) -> None:
        self._store = store
        self._actor = actor
        self._cap = cap

    # -- mutations ------------------------------------------------------------

    def create(
        self,
        path: str,
        content: str,
        *,
        category: str = "general",
        tags: Sequence[str] = (),
    ) -> Memory:
        validate_path(path)
        existing = self._store.get(path)
        if existing is not None and existing.status is MemoryStatus.ACTIVE:
            raise DuplicatePathError(path)
        if self._store.count() >= self._cap:
            raise StoreFullError(self._cap)
        now = utcnow()
        body = canonical_content(content)
        # Recreating over a tombstone continues its version history.
        version = existing.version + 1 if existing else 1
        memory = Memory(
            path=path,
            content=body,
            category=category,
            tags=list(tags),
            version=version,
            content_sha256=content_sha256(body),
            status=MemoryStatus.ACTIVE,
            created_by=existing.created_by if existing else self._actor,
            updated_by=self._actor,
            created=existing.created if existing else now,
            updated=now,
        )
        self._store.put(memory, self._version_record(memory, "create"))
        return memory

    def update(
        self,
        path: str,
        expected_sha256: str,
        *,
        content: str | None = None,
        category: str | None = None,
        tags: Sequence[str] | None = None,
    ) -> Memory:
        current = self._load_active(path)
        self._check_sha(current, expected_sha256)
        body = canonical_content(content) if content is not None else current.content
        memory = current.model_copy(
            update={
                "content": body,
                "content_sha256": content_sha256(body),
                "category": category if category is not None else current.category,
                "tags": list(tags) if tags is not None else list(current.tags),
                "version": current.version + 1,
                "updated_by": self._actor,
                "updated": utcnow(),
            }
        )
        self._store.put(memory, self._version_record(memory, "update"))
        return memory

    def delete(self, path: str, expected_sha256: str) -> Memory:
        current = self._load_active(path)
        self._check_sha(current, expected_sha256)
        tombstone = current.model_copy(
            update={
                "status": MemoryStatus.DELETED,
                "version": current.version + 1,
                "updated_by": self._actor,
                "updated": utcnow(),
            }
        )
        self._store.put(tombstone, self._version_record(tombstone, "delete"))
        return tombstone

    # -- reads ----------------------------------------------------------------

    def read(self, path: str) -> Memory:
        return self._load_active(path)

    def list(self, prefix: str = "/") -> list[Memory]:
        return self._store.list(prefix)

    def search(self, query: str, *, top: int = 5, category: str = "") -> list[SearchHit]:
        return self._store.search(query, top=top, category=category)

    def versions(self, path: str) -> list[MemoryVersion]:
        records = self._store.versions(path)
        if not records:
            raise MemoryNotFoundError(path)
        return records

    def brief(self) -> str:
        """The onboarding pack: every ``onboarding``-category memory in one
        string — the single call a new teammate's agent makes on day one."""
        memories = [m for m in self._store.list("/") if m.category == BRIEF_CATEGORY]
        if not memories:
            return "No onboarding memories yet. Use memory_search for specific questions."
        return "\n\n---\n\n".join(m.content.rstrip("\n") for m in memories)

    # -- internals ------------------------------------------------------------

    def _load_active(self, path: str) -> Memory:
        memory = self._store.get(path)
        if memory is None:
            raise MemoryNotFoundError(path)
        if memory.status is MemoryStatus.DELETED:
            raise MemoryNotFoundError(path, tombstoned=True)
        return memory

    def _check_sha(self, current: Memory, expected: str) -> None:
        if expected != current.content_sha256:
            raise ShaConflictError(
                current.path,
                expected=expected,
                current=current.content_sha256,
                current_version=current.version,
            )

    def _version_record(self, memory: Memory, operation: str) -> MemoryVersion:
        return MemoryVersion(
            path=memory.path,
            version=memory.version,
            operation=operation,
            content=memory.content,
            content_sha256=memory.content_sha256,
            actor=self._actor,
            timestamp=memory.updated,
        )
