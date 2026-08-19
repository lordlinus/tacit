"""Multi-project routing: one server, many projects in one shared index set."""

from tacit.config import ServiceRegistry, Settings, slugify_project
from tacit.tools import TOOL_DEFINITIONS


def test_slugify_project():
    assert slugify_project("Contoso Payments") == "contoso-payments"
    assert slugify_project("my_repo.name") == "my-repo-name"
    assert slugify_project("---") == "default"


def test_every_tool_declares_the_project_property():
    for name, (_desc, props) in TOOL_DEFINITIONS.items():
        assert any(p[0] == "project" for p in props), f"{name} lacks project routing"


def test_a_routed_project_never_changes_who_is_asking():
    """The routed project decides what is operated on; the viewer stays the
    server's own identity, so naming another team cannot borrow its reach."""
    settings = Settings(
        project="alpha",
        team="platform",
        search_endpoint="https://srch-x.search.windows.net",
        actor="t",
    )
    registry = ServiceRegistry(settings)
    assert registry.default_project == "alpha"
    assert settings.viewer().project == "alpha"
    assert settings.viewer().team == "platform"
