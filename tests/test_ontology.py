"""The shared vocabulary: one thing, many names, one answer.

Matching is deterministic and model-free, so it is pinned here directly; the
annotations it produces are written onto chunks by the store (see
test_search_store.py).
"""

import json

import pytest

from tacit.ontology import Entity, Ontology, slugify_entity

GATEWAY = Entity(
    id="payments-gateway",
    name="Payments Gateway",
    aliases=("pmt-gw", "the gateway", "Stripe proxy"),
    kind="system",
    description="Fronts every card transaction.",
)
QUEUE = Entity(id="event-bus", name="Event Bus", aliases=("the bus", "kafka"), kind="system")


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

class TestToolSurface:
    def test_entity_is_offered_to_agents(self):
        from tacit.tools import TOOL_DEFINITIONS

        props = {p[0] for p in TOOL_DEFINITIONS["memory_search"][1]}
        assert {"scope", "entity", "project"} <= props
