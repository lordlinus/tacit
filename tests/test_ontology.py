"""The shared vocabulary: one thing, many names, one answer.

Reach (test_org_memory.py) gets another team's memory into your results. This
gets it there when neither of you uses the same words for the thing.
"""

import json

import pytest

from tacit.local_store import LocalStore
from tacit.ontology import Entity, Ontology, slugify_entity
from tacit.service import MemoryService
from tacit.tools import call_tool

GATEWAY = Entity(
    id="payments-gateway",
    name="Payments Gateway",
    aliases=("pmt-gw", "the gateway", "Stripe proxy"),
    kind="system",
    description="Fronts every card transaction.",
)
QUEUE = Entity(id="event-bus", name="Event Bus", aliases=("the bus", "kafka"), kind="system")


def _service(root, project: str, team: str = "platform") -> MemoryService:
    return MemoryService(
        LocalStore(root, project=project, team=team),
        actor=f"{project}-agent",
        project=project,
        team=team,
    )


@pytest.fixture
def org(tmp_path):
    services = {
        "payments": _service(tmp_path, "payments", team="platform"),
        "search": _service(tmp_path, "search-svc", team="discovery"),
    }
    services["payments"].set_ontology(Ontology(entities=[GATEWAY, QUEUE]))
    return services


class TestMatching:
    def test_the_canonical_name_and_every_alias_resolve(self):
        onto = Ontology(entities=[GATEWAY])
        for phrase in ("Payments Gateway", "pmt-gw", "the gateway", "stripe proxy"):
            assert onto.annotate(f"we changed the {phrase} config") == ["payments-gateway"]

    def test_matching_is_case_insensitive(self):
        onto = Ontology(entities=[GATEWAY])
        assert onto.annotate("PMT-GW is down") == ["payments-gateway"]

    def test_a_substring_of_a_larger_word_is_not_a_match(self):
        """'kafka' must not fire on 'kafkaesque'; word edges are the boundary."""
        onto = Ontology(entities=[QUEUE])
        assert onto.annotate("a kafkaesque approval process") == []
        assert onto.annotate("kafka is lagging") == ["event-bus"]

    def test_the_longest_surface_form_wins(self):
        """A generic alias must not shadow the specific entity that contains it."""
        generic = Entity(id="gateway-generic", name="Gateway", aliases=())
        onto = Ontology(entities=[GATEWAY, generic])
        assert onto.annotate("the Payments Gateway timed out") == ["payments-gateway"]

    def test_several_entities_in_one_passage(self):
        onto = Ontology(entities=[GATEWAY, QUEUE])
        assert onto.annotate("pmt-gw publishes to the bus") == ["event-bus", "payments-gateway"]

    def test_an_empty_vocabulary_annotates_nothing(self):
        assert Ontology().annotate("pmt-gw is down") == []

    def test_vocabulary_text_carries_every_form(self):
        onto = Ontology(entities=[GATEWAY])
        vocab = onto.vocabulary_for(["payments-gateway"])
        for form in ("Payments Gateway", "pmt-gw", "the gateway", "Stripe proxy"):
            assert form in vocab

    def test_an_unknown_id_contributes_nothing(self):
        assert Ontology(entities=[GATEWAY]).vocabulary_for(["nope"]) == ""

    def test_ids_must_be_slugs(self):
        with pytest.raises(ValueError, match="kebab-case"):
            Entity(id="Payments Gateway", name="x")

    def test_slugify_derives_a_usable_id(self):
        assert slugify_entity("Payments Gateway!") == "payments-gateway"

    def test_round_trips_through_json(self):
        onto = Ontology(entities=[GATEWAY, QUEUE])
        assert Ontology.from_dict(json.loads(json.dumps(onto.to_dict()))).to_dict() == onto.to_dict()


class TestCrossVocabularyRetrieval:
    """The payoff: the asker's words never appear in the author's memory."""

    def test_one_teams_alias_is_findable_by_anothers(self, org):
        org["payments"].create(
            "/gotchas/pmt-gw-timeouts.md",
            "# pmt-gw drops connections above 30s\n\n"
            "Set the upstream read timeout to 25s or the proxy closes first.",
            category="gotcha",
        )
        # The asker has never heard the string "pmt-gw".
        hits = org["search"].search("payments gateway connection timeouts")
        assert [h.path for h in hits] == ["/gotchas/pmt-gw-timeouts.md"]
        assert hits[0].project == "payments"

    def test_the_reverse_direction_works_too(self, org):
        org["payments"].create(
            "/gotchas/gateway-retries.md",
            "# The Payments Gateway retries idempotently\n\nSafe to resend on 502.",
        )
        assert org["search"].search("does pmt-gw retry")[0].path == "/gotchas/gateway-retries.md"

    def test_an_entity_named_only_in_the_title_still_annotates_its_sections(self, org):
        org["payments"].create(
            "/runbooks/pmt-gw.md",
            "# pmt-gw runbook\n\n## Draining\n\nStop the upstream, then flip the flag.\n",
        )
        assert org["search"].search("how do I drain the payments gateway")[0].section == "draining"

    def test_without_a_vocabulary_the_two_vocabularies_never_meet(self, tmp_path):
        """The control: this is precisely what the ontology is buying."""
        payments = _service(tmp_path, "payments")
        search = _service(tmp_path, "search-svc", team="discovery")
        payments.create("/gotchas/a.md", "# pmt-gw drops connections above 30s\n\nSet 25s.")
        assert search.search("payments gateway connection timeouts") == []

    def test_vocabulary_does_not_manufacture_matches(self, org):
        """Annotation widens phrasing, it must not make unrelated memories hit."""
        org["payments"].create("/gotchas/ci.md", "# CI cache key must include the lockfile\n\nx")
        assert org["search"].search("payments gateway timeouts") == []


class TestEntityFilter:
    def test_filtering_returns_only_memories_about_that_entity(self, org):
        org["payments"].create("/a.md", "# pmt-gw drops connections\n\nx")
        org["payments"].create("/b.md", "# kafka consumer lag spikes nightly\n\nx")
        org["payments"].create("/c.md", "# CI cache key must include the lockfile\n\nx")
        hits = org["search"].search("drops connections", top=10, entity="payments-gateway")
        assert [h.path for h in hits] == ["/a.md"]

    def test_filtering_excludes_matches_about_something_else(self, org):
        org["payments"].create("/a.md", "# pmt-gw lag is high\n\nlag lag")
        org["payments"].create("/b.md", "# kafka lag is high\n\nlag lag")
        hits = org["search"].search("lag is high", top=10, entity="event-bus")
        assert [h.path for h in hits] == ["/b.md"]


class TestCuration:
    def test_the_vocabulary_is_shared_by_every_project(self, org, tmp_path):
        """One org, one vocabulary — a per-team vocabulary defeats the purpose."""
        assert {e.id for e in org["search"].ontology().entities} == {
            "payments-gateway",
            "event-bus",
        }

    def test_adding_an_alias_replaces_the_entity_by_id(self, org):
        widened = Entity(
            id="payments-gateway", name="Payments Gateway", aliases=(*GATEWAY.aliases, "card-fe")
        )
        others = [e for e in org["payments"].ontology().entities if e.id != widened.id]
        org["payments"].set_ontology(Ontology(entities=[*others, widened]))
        assert org["search"].ontology().get("payments-gateway").aliases[-1] == "card-fe"

    def test_a_memory_written_before_an_alias_existed_is_reachable_after_reindex(self, tmp_path):
        """Annotations live on chunks, so widening the vocabulary is a re-chunk.

        The local backend annotates at query time and so picks it up at once;
        the Azure backend needs `tacit reindex`, which `reindex()` stands in for
        here so the documented flow is exercised in both.
        """
        payments = _service(tmp_path, "payments")
        search = _service(tmp_path, "search-svc", team="discovery")
        payments.create("/a.md", "# card-fe rejects stale credentials\n\nRotate hourly.")
        # Nothing lexical connects the question to the memory...
        assert search.search("payments gateway") == []

        payments.set_ontology(
            Ontology(entities=[Entity(id="payments-gateway", name="Payments Gateway",
                                      aliases=("card-fe",))])
        )
        payments.reindex()
        # ...until the organization records that they are the same thing.
        assert search.search("payments gateway")[0].path == "/a.md"


class TestToolSurface:
    def test_entity_is_offered_to_agents(self):
        from tacit.tools import TOOL_DEFINITIONS

        props = {p[0] for p in TOOL_DEFINITIONS["memory_search"][1]}
        assert {"scope", "entity", "project"} <= props

    def test_entity_filter_reaches_through_call_tool(self, org):
        org["payments"].create("/a.md", "# pmt-gw lag is high\n\nlag")
        org["payments"].create("/b.md", "# kafka lag is high\n\nlag")
        results = call_tool(
            org["search"], "memory_search", {"query": "lag is high", "entity": "event-bus"}
        )
        assert [r["path"] for r in results] == ["/b.md"]
