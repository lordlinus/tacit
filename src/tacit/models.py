"""Domain models.

Memories are path-addressed (Anthropic memory-store style: ``/gotchas/x.md``)
with PEMP-style system-managed bookkeeping: ``version``, ``content_sha256``,
``status`` and timestamps are set by the service, never by callers. The sha
covers the canonical content only, so frontmatter churn never invalidates it.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

PATH_PATTERN = re.compile(r"^(/[a-z0-9][a-z0-9._-]*)+$")
MAX_PATH_LENGTH = 200
MAX_CONTENT_BYTES = 100_000  # Anthropic's per-memory cap (~25k tokens)


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


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


def path_key(path: str) -> str:
    """Search-document key for a path (index keys forbid slashes)."""
    return path.strip("/").replace("/", "--").replace(".", "-")


class Memory(BaseModel):
    """Latest state of one memory."""

    model_config = ConfigDict(frozen=True)

    path: str
    content: str
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
        return path_key(self.path)


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


class SearchHit(BaseModel):
    """A ranked section of a memory: enough to answer from, cheap to transmit.

    Retrieval is progressive. ``content`` is the matched *section*, not the
    whole memory, so a long memory costs only the part that was relevant. If
    even that section is long, ``content`` narrows again to the extract that
    matched — a semantic caption when the ranker supplied one — and
    ``truncated`` is set, meaning "call memory_read for the rest".

    There is deliberately no second field holding both: a snippet alongside the
    text it summarises is pure duplication, and the caller pays for both.
    """

    path: str
    title: str
    category: str
    tags: list[str] = Field(default_factory=list)
    score: float = 0.0
    section: str = ""
    heading: str = ""
    content: str = ""
    truncated: bool = False
