"""Domain models.

Memories are path-addressed (Anthropic memory-store style: ``/gotchas/x.md``)
with PEMP-style system-managed bookkeeping: ``version``, ``content_sha256``,
``status`` and timestamps are set by the service, never by callers. The sha
covers the canonical content only, so frontmatter churn never invalidates it.

A memory is addressed by ``(project, path)``, not by path alone: one store
serves the whole organization, and two teams may legitimately both keep a
``/gotchas/retry.md``. ``project`` says which repo owns it, ``team`` which
group of people, and ``visibility`` who outside the owning project may read it.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

PATH_PATTERN = re.compile(r"^(/[a-z0-9][a-z0-9._-]*)+$")
PROJECT_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_PATH_LENGTH = 200
MAX_CONTENT_BYTES = 100_000  # Anthropic's per-memory cap (~25k tokens)
DEFAULT_PROJECT = "default"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class Visibility(StrEnum):
    """Who may read a memory from outside the project that owns it.

    ``ORG`` is the default because the point of an organizational memory is
    that a lesson learned once is not relearned by every other team. ``TEAM``
    and ``PRIVATE`` are the deliberate opt-outs for work that should not
    travel: an unannounced project, a team-internal process note.
    """

    PRIVATE = "private"  # only the owning project
    TEAM = "team"  # the owning team's projects
    ORG = "org"  # the whole organization


class SearchScope(StrEnum):
    """How wide a search reaches.

    ``PROJECT_PLUS_ORG`` is the default: an agent asking a question gets its
    own project's memories *and* whatever the rest of the organization has
    published, ranked together with a bias toward home. Widening the default
    is what turns a per-team store into organizational memory.
    """

    PROJECT = "project"
    PROJECT_PLUS_ORG = "project+org"
    ORG = "org"


#: Multiplier applied to a hit from the caller's own project. Local knowledge
#: is more likely to be actionable than a neighbouring team's, but a strongly
#: matching org memory must still be able to outrank a weak local one — hence
#: a boost rather than a hard sort key.
HOME_PROJECT_BOOST = 1.25


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_content(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip("\n") + "\n"


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_path(path: str) -> str:
    if len(path) > MAX_PATH_LENGTH or not PATH_PATTERN.match(path):
        raise ValueError(
            "path must look like /dir/name.md (lowercase, digits, . _ -, "
            f"leading slash, max {MAX_PATH_LENGTH} chars); got {path!r}"
        )
    return path


def validate_project(project: str) -> str:
    if not PROJECT_PATTERN.match(project):
        raise ValueError(f"project must be a kebab-case slug; got {project!r}")
    return project


def path_key(path: str) -> str:
    """Path component of a search-document key (index keys forbid slashes)."""
    return path.strip("/").replace("/", "--").replace(".", "-")


def doc_key(project: str, path: str) -> str:
    """Key of a memory in the shared org-wide index.

    The store holds every project, so the key must be scoped by project or two
    teams' ``/gotchas/retry.md`` would collide. Keys are write-only identifiers
    — ``project`` and ``path`` are also stored as their own fields, so nothing
    ever needs to parse one back apart.
    """
    return f"{project}--{path_key(path)}"


class Memory(BaseModel):
    """Latest state of one memory."""

    model_config = ConfigDict(frozen=True)

    path: str
    content: str
    project: str = DEFAULT_PROJECT
    team: str = ""
    visibility: Visibility = Visibility.ORG
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)
    content_sha256: str = ""
    status: MemoryStatus = MemoryStatus.ACTIVE
    created_by: str = "unknown"
    updated_by: str = "unknown"
    created: datetime = Field(default_factory=utcnow)
    updated: datetime = Field(default_factory=utcnow)

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return validate_path(value)

    @field_validator("project")
    @classmethod
    def _validate_project(cls, value: str) -> str:
        return validate_project(value)

    @field_validator("content")
    @classmethod
    def _canonicalize(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise ValueError(f"content exceeds {MAX_CONTENT_BYTES} bytes; split the memory")
        return canonical_content(value)

    @property
    def title(self) -> str:
        for line in self.content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return self.path

    @property
    def key(self) -> str:
        return doc_key(self.project, self.path)

    def readable_by(self, project: str, team: str) -> bool:
        """Can a caller working in ``project`` (on ``team``) read this memory?

        The single place the visibility rules live, so the two backends cannot
        disagree about what leaks. The owning project always sees its own
        memories regardless of visibility.
        """
        if self.project == project:
            return True
        if self.visibility is Visibility.ORG:
            return True
        if self.visibility is Visibility.TEAM:
            return bool(team) and self.team == team
        return False


class MemoryVersion(BaseModel):
    """One immutable entry in a memory's audit trail."""

    model_config = ConfigDict(frozen=True)

    path: str
    version: int
    operation: str  # create | update | delete
    content: str
    content_sha256: str
    actor: str
    timestamp: datetime
    project: str = DEFAULT_PROJECT

    @property
    def key(self) -> str:
        return f"{doc_key(self.project, self.path)}-v{self.version}"


class SearchHit(BaseModel):
    """A ranked section of a memory: enough to answer from, cheap to transmit.

    Retrieval is progressive. ``content`` is the matched *section*, not the
    whole memory, so a long memory costs only the part that was relevant. If
    even that section is long, ``content`` narrows again to the extract that
    matched — a semantic caption when the ranker supplied one — and
    ``truncated`` is set, meaning "call memory_read for the rest".

    There is deliberately no second field holding both: a snippet alongside the
    text it summarises is pure duplication, and the caller pays for both.

    ``project``/``team`` say where the knowledge came from. A hit from another
    team is worth acting on differently from one's own, so the origin travels
    with the answer rather than being inferred.
    """

    path: str
    title: str
    category: str
    project: str = DEFAULT_PROJECT
    team: str = ""
    tags: list[str] = Field(default_factory=list)
    score: float = 0.0
    section: str = ""
    heading: str = ""
    content: str = ""
    truncated: bool = False
