"""The overlap graph: what it shows, and what it must never show.

The graph aggregates across every project, which makes it the most likely place
for a visibility leak to appear — and the least likely place to notice one,
because a leak shows up as a slightly larger number rather than as an error.
"""

import json

import pytest

from tacit.graph import build_overlap_graph, entity_node_id, project_node_id
from tacit.local_store import LocalStore
from tacit.models import SearchScope, Visibility
from tacit.ontology import Entity, Ontology
from tacit.service import MemoryService

GATEWAY = Entity(id="payments-gateway", name="Payments Gateway",
                 aliases=("pmt-gw", "the gateway"), kind="system")
BUS = Entity(id="event-bus", name="Event Bus", aliases=("kafka",), kind="system")


def _service(root, project: str, team: str = "platform") -> MemoryService:
    return MemoryService(
        LocalStore(root, project=project, team=team),
        actor=f"{project}-agent", project=project, team=team,
    )


@pytest.fixture
def org(tmp_path):
    services = {
        "payments": _service(tmp_path, "payments", team="platform"),
        "search": _service(tmp_path, "search-svc", team="discovery"),
    }
    services["payments"].set_ontology(Ontology(entities=[GATEWAY, BUS]))
    return services


class TestOverlap:
    def test_an_entity_two_teams_know_about_is_marked_shared(self, org):
        org["payments"].create("/a.md", "# pmt-gw drops connections\n\nRaise the timeout.")
        org["search"].create("/b.md", "# Crawler calls the gateway directly\n\nBudget 25s.")
        g = org["search"].graph()
        node = next(n for n in g["nodes"] if n["id"] == entity_node_id("payments-gateway"))
        assert node["shared"] is True
        assert node["projects"] == 2
        assert g["stats"]["shared_entities"] == 1

    def test_an_entity_only_one_team_knows_is_not_shared(self, org):
        org["payments"].create("/a.md", "# kafka consumer lag\n\nx")
        g = org["payments"].graph()
        node = next(n for n in g["nodes"] if n["id"] == entity_node_id("event-bus"))
        assert node["shared"] is False
        assert node["projects"] == 1

    def test_edges_connect_projects_to_the_entities_they_wrote_about(self, org):
        org["payments"].create("/a.md", "# pmt-gw drops connections\n\nx")
        org["payments"].create("/b.md", "# the gateway needs a warm pool\n\nx")
        g = org["payments"].graph()
        edge = next(e for e in g["edges"]
                    if e["source"] == project_node_id("payments")
                    and e["target"] == entity_node_id("payments-gateway"))
        assert edge["weight"] == 2, "weight is how many memories, not how many mentions"

    def test_clicking_an_entity_yields_the_memories_behind_it(self, org):
        org["payments"].create("/gotchas/a.md", "# pmt-gw drops connections\n\nx",
                               category="gotcha")
        org["search"].create("/notes/b.md", "# gateway budget\n\nthe gateway is slow")
        g = org["search"].graph()
        mems = g["memories"][entity_node_id("payments-gateway")]
        assert {m["path"] for m in mems} == {"/gotchas/a.md", "/notes/b.md"}
        foreign = next(m for m in mems if m["path"] == "/gotchas/a.md")
        assert foreign["project"] == "payments" and foreign["team"] == "platform"

    def test_a_project_with_no_vocabulary_hits_is_left_off(self, org):
        """An unconnected node says nothing about overlap and clutters the view."""
        org["search"].create("/misc.md", "# CI cache key must include the lockfile\n\nx")
        g = org["search"].graph()
        assert g["nodes"] == []
        assert g["stats"]["visible_memories"] == 1, "still counted, just not drawn"

    def test_an_empty_vocabulary_yields_an_empty_graph_not_an_error(self, tmp_path):
        service = _service(tmp_path, "payments")
        service.create("/a.md", "# Something happened\n\nx")
        g = service.graph()
        assert g["nodes"] == [] and g["edges"] == []
        assert g["stats"]["vocabulary_size"] == 0

    def test_the_home_project_is_marked_for_orientation(self, org):
        org["payments"].create("/a.md", "# pmt-gw\n\nx")
        g = org["search"].graph()
        home = next(n for n in g["nodes"] if n["id"] == project_node_id("payments"))
        assert home["shared"] is False, "payments is not the viewer here"
        assert g["stats"]["home_project"] == "search-svc"

    def test_the_payload_is_json_serialisable(self, org):
        """It is returned straight over HTTP, so a stray dataclass would 500."""
        org["payments"].create("/a.md", "# pmt-gw\n\nx")
        assert json.loads(json.dumps(org["payments"].graph()))


class TestGraphRespectsVisibility:
    """A leak here is a larger number, not an exception — so assert precisely."""

    def test_a_private_memory_contributes_no_node_edge_or_count(self, org):
        org["payments"].create(
            "/secret/plan.md",
            "# pmt-gw will be replaced by Project Zeus\n\nUnannounced.",
            visibility=Visibility.PRIVATE,
        )
        g = org["search"].graph()
        assert g["nodes"] == [], "a private memory must not create an entity node"
        assert g["edges"] == []
        assert g["memories"] == {}
        assert g["stats"]["visible_memories"] == 0

    def test_a_private_memory_does_not_inflate_a_shared_entitys_counts(self, org):
        """The subtle leak: the node legitimately exists, but its numbers would
        silently reveal that another team wrote something more about it."""
        org["search"].create("/mine.md", "# the gateway is slow\n\nx")
        org["payments"].create("/secret.md", "# pmt-gw rewrite\n\nx",
                               visibility=Visibility.PRIVATE)
        g = org["search"].graph()
        node = next(n for n in g["nodes"] if n["id"] == entity_node_id("payments-gateway"))
        assert node["memories"] == 1
        assert node["projects"] == 1
        assert node["shared"] is False, "must not appear shared on the strength of a hidden memory"

    def test_a_team_memory_is_visible_to_the_team_and_not_beyond(self, tmp_path, org):
        org["payments"].create("/process.md", "# the gateway oncall rotation\n\nx",
                               visibility=Visibility.TEAM)
        assert org["search"].graph()["nodes"] == []
        sibling = _service(tmp_path, "checkout", team="platform")
        node_ids = {n["id"] for n in sibling.graph()["nodes"]}
        assert entity_node_id("payments-gateway") in node_ids

    def test_scope_narrows_the_graph(self, org):
        org["payments"].create("/a.md", "# pmt-gw drops connections\n\nx")
        org["search"].create("/b.md", "# kafka lag\n\nx")
        own = org["search"].graph(scope=SearchScope.PROJECT)
        assert {n["id"] for n in own["nodes"] if n["kind"] == "entity"} == {
            entity_node_id("event-bus")
        }
        elsewhere = org["search"].graph(scope=SearchScope.ORG)
        assert {n["id"] for n in elsewhere["nodes"] if n["kind"] == "entity"} == {
            entity_node_id("payments-gateway")
        }


class TestBuilderIsPure:
    def test_it_reports_only_what_it_was_given(self):
        """The builder trusts its input to be pre-filtered; that contract is why
        the visibility rules live in one place instead of two."""
        from tacit.models import Memory

        memories = [Memory(path="/a.md", content="# pmt-gw\n\nx", project="p", team="t")]
        g = build_overlap_graph(memories, Ontology(entities=[GATEWAY]), home_project="p")
        assert g["stats"]["visible_memories"] == 1
        assert len(g["nodes"]) == 2  # one entity, one project

    def test_annotation_follows_the_current_vocabulary(self):
        """Recomputed at build time, so the graph is never stale relative to the
        vocabulary — only the chunks index can be, and `reindex` fixes that."""
        from tacit.models import Memory

        memories = [Memory(path="/a.md", content="# card-fe rejects tokens\n\nx", project="p")]
        before = build_overlap_graph(memories, Ontology(entities=[GATEWAY]))
        assert before["nodes"] == []
        widened = Ontology(entities=[Entity(id="payments-gateway", name="Payments Gateway",
                                            aliases=("card-fe",))])
        after = build_overlap_graph(memories, widened)
        assert entity_node_id("payments-gateway") in {n["id"] for n in after["nodes"]}
