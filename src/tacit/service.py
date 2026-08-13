"""The memory service: every mutation goes through here.

Enforces the platform invariants over any MemoryStore backend:
immutable versions, sha-preconditioned mutations, tombstone deletes,
and the store cap. Reads are pass-throughs.

The service also owns *provenance*: it stamps every memory with the project
and team writing it and the visibility it is published under. Callers never
supply those — an agent that could choose its own project could write into
another team's namespace, and one that could forge a team could read that
team's private notes.
"""

from __future__ import annotations

from collections.abc import Sequence

from .errors import DuplicatePathError, MemoryNotFoundError, ShaConflictError, StoreFullError
from .models import (
    DEFAULT_PROJECT,
    Memory,
    MemoryStatus,
    MemoryVersion,
    SearchHit,
    SearchScope,
    Visibility,
    canonical_content,
    content_sha256,
    utcnow,
    validate_path,
)
from .store import MemoryStore

DEFAULT_STORE_CAP = 2000
BRIEF_CATEGORY = "onboarding"


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        *,
        actor: str = "unknown",
        project: str = "",
        team: str = "",
        default_visibility: Visibility = Visibility.ORG,
        cap: int = DEFAULT_STORE_CAP,
        viewer=None,
    ) -> None:
        self._store = store
        self._actor = actor
        # The store is scoped to a project at construction; trust it over an
        # unset argument so the two can never disagree about what is being
        # written where.
        self._project = project or getattr(store, "project", DEFAULT_PROJECT)
        self._team = team or getattr(store, "team", "")
        self._default_visibility = default_visibility
        self._cap = cap
        # Permission is evaluated against the viewer, never against the routed
        # project — otherwise naming a project would grant its privileges.
        # Constructed directly (no registry) means the caller *is* the project.
        from .scope import Viewer

        self._viewer = viewer or Viewer(project=self._project, team=self._team)

    @property
    def project(self) -> str:
        return self._project

    @property
    def team(self) -> str:
        return self._team

    # -- mutations ------------------------------------------------------------

    def create(
        self,
        path: str,
        content: str,
        *,
        category: str = "general",
        tags: Sequence[str] = (),
        visibility: Visibility | str | None = None,
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
            project=self._project,
            team=self._team,
            visibility=self._visibility(visibility),
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
        visibility: Visibility | str | None = None,
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
                "visibility": (
                    self._visibility(visibility)
                    if visibility is not None
                    else current.visibility
                ),
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
        return [m for m in self._store.list(prefix) if self._visible(m)]

    def reindex(self) -> int:
        """Rebuild any derived retrieval index from the system of record."""
        return self._store.reindex()

    def search(
        self,
        query: str,
        *,
        top: int = 5,
        category: str = "",
        scope: SearchScope | str | None = None,
        entity: str = "",
    ) -> list[SearchHit]:
        return self._store.search(
            query, top=top, category=category, scope=scope, entity=entity
        )

    # -- vocabulary -----------------------------------------------------------

    def ontology(self):
        """The organization's controlled vocabulary."""
        return self._store.load_ontology()

    def graph(self, scope: SearchScope | str | None = None) -> dict:
        """The cross-team overlap graph over everything this viewer may see.

        Built from :meth:`MemoryStore.visible_memories`, so it can never show a
        node, an edge or a count derived from a memory the caller could not
        have found through search.
        """
        from .graph import build_overlap_graph

        return build_overlap_graph(
            self._store.visible_memories(scope),
            self._store.load_ontology(),
            home_project=self._project,
        )

    def set_ontology(self, ontology) -> int:
        """Replace the vocabulary.

        Annotations are written onto chunks, so an existing store keeps its old
        annotations until re-chunked; callers follow this with ``reindex()``.
        """
        return self._store.save_ontology(ontology)

    def versions(self, path: str) -> list[MemoryVersion]:
        # Gate on the memory itself: the audit trail carries the full content of
        # every version, so exposing it would defeat the check on `read`. A
        # tombstone is deliberately still readable here — the audit trail
        # outliving the memory is the point of tombstoning.
        memory = self._store.get(path)
        if memory is None or not self._visible(memory):
            raise MemoryNotFoundError(path)
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

    def _visibility(self, requested: Visibility | str | None) -> Visibility:
        if requested is None or requested == "":
            return self._default_visibility
        try:
            return Visibility(str(requested).strip().lower())
        except ValueError as exc:
            allowed = ", ".join(v.value for v in Visibility)
            raise ValueError(
                f"unknown visibility {requested!r}; use one of: {allowed}"
            ) from exc

    def _visible(self, memory: Memory) -> bool:
        """May this server's viewer read this memory at all?

        Applied to every direct read as well as to search, because a routed
        project must not turn ``memory_read`` into a way around the filter.
        """
        return self._viewer.sees(memory)

    def _load_active(self, path: str) -> Memory:
        memory = self._store.get(path)
        if memory is None:
            raise MemoryNotFoundError(path)
        if memory.status is MemoryStatus.DELETED:
            raise MemoryNotFoundError(path, tombstoned=True)
        if not self._visible(memory):
            # Report it as absent rather than forbidden: confirming that a path
            # exists in another team's project is itself a disclosure.
            raise MemoryNotFoundError(path)
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
            project=memory.project,
            version=memory.version,
            operation=operation,
            content=memory.content,
            content_sha256=memory.content_sha256,
            actor=self._actor,
            timestamp=memory.updated,
        )
