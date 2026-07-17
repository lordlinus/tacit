"""Platform invariants over the local backend: immutability, sha preconditions,
tombstones, search relevance, brief()."""

import pytest

from teamlore.errors import (
    DuplicatePathError,
    MemoryNotFoundError,
    ShaConflictError,
    StoreFullError,
)
from teamlore.local_store import LocalStore
from teamlore.service import MemoryService


@pytest.fixture
def service(tmp_path):
    return MemoryService(LocalStore(tmp_path), actor="alice")


def test_create_and_read(service):
    memory = service.create(
        "/gotchas/retry.md", "# Retry on 429\n\nBack off per-file.", category="gotcha", tags=["http"]
    )
    assert memory.version == 1
    assert memory.title == "Retry on 429"
    read = service.read("/gotchas/retry.md")
    assert read.content_sha256 == memory.content_sha256
    assert read.created_by == "alice"


def test_create_duplicate_rejected(service):
    service.create("/a.md", "# A")
    with pytest.raises(DuplicatePathError):
        service.create("/a.md", "# A again")


def test_path_validation(service):
    with pytest.raises(ValueError):
        service.create("no-leading-slash.md", "# X")
    with pytest.raises(ValueError):
        service.create("/Bad Caps.md", "# X")


def test_update_requires_matching_sha(service):
    memory = service.create("/a.md", "# A\n\nv1")
    updated = service.update("/a.md", memory.content_sha256, content="# A\n\nv2")
    assert updated.version == 2
    with pytest.raises(ShaConflictError) as exc:
        service.update("/a.md", memory.content_sha256, content="# A\n\nv3")
    result = exc.value.as_result()
    assert result["error"] == "sha_conflict"
    assert result["current_version"] == 2
    assert result["current_sha256"] == updated.content_sha256


def test_delete_is_tombstone_with_history(service):
    memory = service.create("/a.md", "# A")
    service.delete("/a.md", memory.content_sha256)
    with pytest.raises(MemoryNotFoundError) as exc:
        service.read("/a.md")
    assert exc.value.tombstoned
    versions = service.versions("/a.md")
    assert [v.operation for v in versions] == ["create", "delete"]
    assert versions[0].content.startswith("# A")


def test_recreate_over_tombstone_continues_versions(service):
    memory = service.create("/a.md", "# A")
    service.delete("/a.md", memory.content_sha256)
    recreated = service.create("/a.md", "# A reborn")
    assert recreated.version == 3
    assert [v.operation for v in service.versions("/a.md")] == ["create", "delete", "create"]


def test_list_prefix_excludes_tombstones(service):
    service.create("/gotchas/a.md", "# A")
    b = service.create("/gotchas/b.md", "# B")
    service.create("/conventions/c.md", "# C")
    service.delete("/gotchas/b.md", b.content_sha256)
    assert [m.path for m in service.list("/gotchas/")] == ["/gotchas/a.md"]
    assert len(service.list("/")) == 2


def test_search_ranks_title_matches_first(service):
    service.create("/gotchas/stale-wheel.md", "# Stale wheel on reinstall\n\nuv caches built wheels by version.", category="gotcha")
    service.create("/architecture/overview.md", "# Architecture\n\nThe CLI wheels through modules.", category="architecture")
    hits = service.search("stale wheel reinstall")
    assert hits[0].path == "/gotchas/stale-wheel.md"
    assert hits[0].content  # full content returned, enough to answer from


def test_search_category_filter(service):
    service.create("/a.md", "# Deploy steps", category="onboarding")
    service.create("/b.md", "# Deploy gotcha", category="gotcha")
    hits = service.search("deploy", category="gotcha")
    assert [h.path for h in hits] == ["/b.md"]


def test_brief_concatenates_onboarding_memories(service):
    service.create("/onboarding/setup.md", "# Setup\n\nuv sync", category="onboarding")
    service.create("/gotchas/x.md", "# X", category="gotcha")
    brief = service.brief()
    assert "uv sync" in brief
    assert "# X" not in brief


def test_store_cap(tmp_path):
    service = MemoryService(LocalStore(tmp_path), actor="alice", cap=2)
    service.create("/a.md", "# A")
    service.create("/b.md", "# B")
    with pytest.raises(StoreFullError):
        service.create("/c.md", "# C")


def test_persistence_across_instances(tmp_path):
    service = MemoryService(LocalStore(tmp_path), actor="alice")
    memory = service.create("/a.md", "# A")
    reopened = MemoryService(LocalStore(tmp_path), actor="bob")
    assert reopened.read("/a.md").content_sha256 == memory.content_sha256
    updated = reopened.update("/a.md", memory.content_sha256, content="# A v2")
    assert updated.updated_by == "bob"
    assert updated.created_by == "alice"
