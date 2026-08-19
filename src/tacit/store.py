"""The storage protocol the Azure AI Search backend implements.

Stores are dumb: they persist and query documents. Validation, optimistic
concurrency, tombstones, and version appending live in the service layer, so
the rules hold no matter what a store does.
"""

from __future__ import annotations

from typing import Protocol

from .models import Memory, MemoryVersion, SearchHit, SearchScope


class MemoryStore(Protocol):
    #: Project this store reads and writes on behalf of. The store is
    #: organization-wide; this is the scope every non-search operation uses.
    project: str

    #: Owning team, used to resolve ``visibility="team"`` memories.
    team: str

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

    def visible_memories(self, scope: "SearchScope | str | None" = None) -> list[Memory]:
        """Every active memory the viewer may see, across every project.

        Unlike :meth:`list` this deliberately crosses project boundaries, under
        the same visibility rules search obeys (see :mod:`tacit.scope`).
        """
        ...

    def search(
        self,
        query: str,
        *,
        top: int = 5,
        category: str = "",
        scope: "SearchScope | str | None" = None,
        entity: str = "",
    ) -> list[SearchHit]:
        """Ranked search over active memories; hits carry the matched section.

        ``scope`` widens or narrows how far the search reaches across projects;
        a store must never return a memory the caller's project and team are
        not permitted to see (see :mod:`tacit.scope`). ``entity`` restricts to
        chunks annotated with a canonical entity id from the shared vocabulary.
        """
        ...

    def load_ontology(self, *, refresh: bool = False, strict: bool = False):
        """The organization's controlled vocabulary (see :mod:`tacit.ontology`).

        ``strict`` makes an unreachable vocabulary raise instead of degrading to
        an empty one; callers that derive a mutation from the result must use it.
        """
        ...

    def save_ontology(self, ontology) -> int:
        """Replace the vocabulary; returns the number of entities stored."""
        ...

    def reindex(self) -> int:
        """Rebuild any derived retrieval index; returns memories processed."""
        ...

    def versions(self, path: str) -> list[MemoryVersion]:
        """Audit trail for a path, oldest first."""
        ...

    def count(self) -> int:
        """Number of active memories (for the store cap)."""
        ...
