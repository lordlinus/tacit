"""Multi-project routing: one server, many stores."""

from tacit.config import ServiceRegistry, Settings, slugify_project
from tacit.tools import TOOL_DEFINITIONS, call_tool


def _registry(tmp_path, default="alpha"):
    return ServiceRegistry(
        Settings(backend="local", local_root=str(tmp_path), project=default, actor="t")
    )


def test_slugify_project():
    assert slugify_project("Contoso Payments") == "contoso-payments"
    assert slugify_project("my_repo.name") == "my-repo-name"
    assert slugify_project("---") == "default"


def test_every_tool_declares_the_project_property():
    for name, (_desc, props) in TOOL_DEFINITIONS.items():
        assert any(p[0] == "project" for p in props), f"{name} lacks project routing"


def test_calls_route_to_separate_stores(tmp_path):
    registry = _registry(tmp_path)
    call_tool(registry, "memory_create", {"path": "/a.md", "content": "# Alpha fact", "project": "alpha"})
    call_tool(registry, "memory_create", {"path": "/b.md", "content": "# Beta fact", "project": "beta"})

    alpha = call_tool(registry, "memory_list", {"project": "alpha"})
    beta = call_tool(registry, "memory_list", {"project": "beta"})
    assert [m["path"] for m in alpha] == ["/a.md"]
    assert [m["path"] for m in beta] == ["/b.md"]


def test_missing_project_uses_the_default(tmp_path):
    registry = _registry(tmp_path, default="alpha")
    call_tool(registry, "memory_create", {"path": "/a.md", "content": "# Alpha"})
    assert call_tool(registry, "memory_read", {"path": "/a.md", "project": "alpha"})["title"] == "Alpha"


def test_project_names_are_normalized(tmp_path):
    registry = _registry(tmp_path)
    call_tool(registry, "memory_create", {"path": "/a.md", "content": "# X", "project": "Contoso Payments"})
    assert call_tool(registry, "memory_list", {"project": "contoso-payments"})


def test_plain_service_still_accepted(tmp_path):
    """Single-project callers (tests, CLI) pass a MemoryService directly."""
    from tacit.local_store import LocalStore
    from tacit.service import MemoryService

    service = MemoryService(LocalStore(tmp_path), actor="t")
    created = call_tool(service, "memory_create", {"path": "/a.md", "content": "# A", "project": "ignored"})
    assert created["version"] == 1
