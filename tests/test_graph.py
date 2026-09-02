"""The overlap graph's ``projects`` focus.

A shared store holds every team's memories; the graph is the picture that
argues for that. Focusing on a subset must be a lens on what is already
visible — it can hide, but it must never reveal — and both HTTP servers must
parse the URL value the same way.
"""

from __future__ import annotations

import pytest

from tacit.graph import build_overlap_graph, parse_projects
from tacit.models import Memory
from tacit.ontology import Entity, Ontology

VAULT = Entity(id="key-vault", name="Key Vault", aliases=("kv",), kind="system")
QUEUE = Entity(id="event-bus", name="Event Bus", aliases=("the bus",), kind="system")
ONTOLOGY = Ontology(entities=[VAULT, QUEUE])

MEMORIES = [
    Memory(path="/a.md", content="# Rotation\nKey Vault rotates the key.", project="atlas"),
    Memory(path="/b.md", content="# Verify\nKey Vault versions matter.", project="onboarding"),
    Memory(path="/c.md", content="# Lag\nThe bus lags under load.", project="aws"),
    Memory(path="/d.md", content="# Also\nKey Vault again, and the bus.", project="aws"),
]


def project_labels(graph: dict) -> list[str]:
    return sorted(n["label"] for n in graph["nodes"] if n["kind"] == "project")


def entity_ids(graph: dict) -> dict[str, bool]:
    return {n["id"]: n["shared"] for n in graph["nodes"] if n["kind"] == "entity"}


class TestFocus:
    def test_no_focus_draws_everything_visible(self):
        graph = build_overlap_graph(MEMORIES, ONTOLOGY)
        assert project_labels(graph) == ["atlas", "aws", "onboarding"]
        assert graph["stats"]["focus"] == []
        assert graph["stats"]["visible_projects"] == ["atlas", "aws", "onboarding"]

    def test_focus_hides_other_projects_and_recomputes_overlap(self):
        graph = build_overlap_graph(MEMORIES, ONTOLOGY, projects=["atlas", "onboarding"])
        assert project_labels(graph) == ["atlas", "onboarding"]
        # Key Vault is still shared (two focused projects); the bus, known only
        # to the hidden project, is gone rather than drawn adrift.
        assert entity_ids(graph) == {"entity:key-vault": True}
        assert graph["stats"]["visible_memories"] == 2
        assert graph["stats"]["focus"] == ["atlas", "onboarding"]

    def test_focus_keeps_the_full_project_list_for_the_picker(self):
        graph = build_overlap_graph(MEMORIES, ONTOLOGY, projects=["atlas"])
        assert graph["stats"]["visible_projects"] == ["atlas", "aws", "onboarding"]
        assert graph["stats"]["projects"] == 1

    def test_focus_on_a_project_the_viewer_cannot_see_reveals_nothing(self):
        # ``memories`` is already visibility-filtered upstream; a focus on a
        # project absent from it yields an empty picture, never extra rows.
        graph = build_overlap_graph(MEMORIES, ONTOLOGY, projects=["private-team"])
        assert graph["nodes"] == []
        assert graph["stats"]["visible_memories"] == 0

    def test_malformed_slug_is_rejected(self):
        with pytest.raises(ValueError):
            build_overlap_graph(MEMORIES, ONTOLOGY, projects=["Not A Slug"])


class TestParseProjects:
    def test_splits_trims_dedupes_and_sorts(self):
        assert parse_projects(" onboarding, atlas,,atlas ") == ["atlas", "onboarding"]

    def test_empty_means_no_focus(self):
        assert parse_projects("") == []
        assert parse_projects(" , ") == []

    def test_malformed_entry_raises_for_a_400(self):
        with pytest.raises(ValueError):
            parse_projects("atlas,Bad Slug")


def test_page_carries_the_focus_in_the_url():
    """The whole point of the filter is a bookmarkable, pre-focused demo URL."""
    from tacit.ui import PAGE

    assert 'QS.get("projects")' in PAGE
    assert 'projects: FOCUS.join(",")' in PAGE
    assert 'id="focus"' in PAGE
