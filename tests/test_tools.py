"""The shared MCP tool surface: dispatch, structured errors, schemas."""

import pytest

from teamlore.local_store import LocalStore
from teamlore.service import MemoryService
from teamlore.tools import TOOL_DEFINITIONS, call_tool


@pytest.fixture
def service(tmp_path):
    return MemoryService(LocalStore(tmp_path), actor="agent")


def test_create_read_roundtrip(service):
    created = call_tool(
        service,
        "memory_create",
        {"path": "/gotchas/a.md", "content": "# A gotcha\n\nDetails.", "category": "gotcha", "tags": "ci, uv"},
    )
    assert created["version"] == 1
    assert created["tags"] == ["ci", "uv"]
    read = call_tool(service, "memory_read", {"path": "/gotchas/a.md"})
    assert read["content_sha256"] == created["content_sha256"]


def test_search_returns_ranked_hits(service):
    call_tool(service, "memory_create", {"path": "/a.md", "content": "# Token refresh\n\nProxy mints tokens."})
    hits = call_tool(service, "memory_search", {"query": "token refresh"})
    assert hits[0]["path"] == "/a.md"


def test_sha_conflict_is_structured_not_raised(service):
    created = call_tool(service, "memory_create", {"path": "/a.md", "content": "# A"})
    call_tool(service, "memory_update", {"path": "/a.md", "expected_sha256": created["content_sha256"], "content": "# A2"})
    stale = call_tool(
        service,
        "memory_update",
        {"path": "/a.md", "expected_sha256": created["content_sha256"], "content": "# A3"},
    )
    assert stale["error"] == "sha_conflict"
    assert "memory_read" in stale["hint"]


def test_not_found_and_duplicate_are_structured(service):
    assert call_tool(service, "memory_read", {"path": "/nope.md"})["error"] == "not_found"
    call_tool(service, "memory_create", {"path": "/a.md", "content": "# A"})
    assert call_tool(service, "memory_create", {"path": "/a.md", "content": "# A"})["error"] == "duplicate_path"


def test_delete_then_versions(service):
    created = call_tool(service, "memory_create", {"path": "/a.md", "content": "# A"})
    call_tool(service, "memory_delete", {"path": "/a.md", "expected_sha256": created["content_sha256"]})
    versions = call_tool(service, "memory_versions", {"path": "/a.md"})
    assert [v["operation"] for v in versions] == ["create", "delete"]


def test_brief_tool(service):
    call_tool(service, "memory_create", {"path": "/onboarding/start.md", "content": "# Start here", "category": "onboarding"})
    assert "Start here" in call_tool(service, "memory_brief", {})["brief"]


def test_unknown_tool_raises(service):
    with pytest.raises(ValueError):
        call_tool(service, "memory_nuke", {})


def test_every_definition_dispatches(service):
    """Each declared tool must be handled by call_tool (no drift)."""
    created = call_tool(service, "memory_create", {"path": "/a.md", "content": "# A", "category": "onboarding"})
    smoke_args = {
        "memory_search": {"query": "a"},
        "memory_brief": {},
        "memory_read": {"path": "/a.md"},
        "memory_list": {},
        "memory_create": {"path": "/b.md", "content": "# B"},
        "memory_update": {"path": "/a.md", "expected_sha256": created["content_sha256"], "content": "# A2"},
        "memory_versions": {"path": "/a.md"},
        "memory_delete": {"path": "/b.md", "expected_sha256": "deadbeef"},  # conflict is fine
    }
    assert set(smoke_args) == set(TOOL_DEFINITIONS)
    for name, args in smoke_args.items():
        call_tool(service, name, args)  # must not raise
