"""SearchStore request shaping, with the network stubbed.

These pin the parts that only the Azure backend has: the derived chunks index,
the semantic-ranker downgrade, snippet economy, and OData escaping. They assert
on the request bodies we send, because a wrong body fails silently as bad
ranking rather than as an error.
"""

import pytest

from tacit.config import Settings
from tacit.models import Memory, MemoryStatus, MemoryVersion, SearchScope, Visibility, utcnow
from tacit.search_index import SCORING_PROFILE, SEMANTIC_CONFIG, index_names
from tacit.search_store import SearchStore, _extract_from, odata_quote


class FakeSearch:
    """Records every (index, suffix, body) and replays queued responses."""

    def __init__(self, responses=None):
        self.calls: list[tuple[str, str, dict]] = []
        self.responses = list(responses or [])
        self.errors: dict[str, Exception] = {}

    def __call__(self, index, suffix, body):
        self.calls.append((index, suffix, body))
        for marker, exc in self.errors.items():
            if marker in str(body):
                raise exc
        return self.responses.pop(0) if self.responses else {"value": []}

    def bodies(self, suffix):
        return [b for _, s, b in self.calls if s == suffix]


def _doc(content: str, captions: list[str] | None = None) -> dict:
    doc = {
        "path": "/runbooks/oncall.md",
        "project": "demo",
        "team": "platform",
        "title": "Oncall",
        "category": "runbooks",
        "tags": ["oncall"],
        "section": "refunds",
        "heading": "Refunds",
        "content": content,
        "@search.rerankerScore": 3.0,
    }
    if captions:
        doc["@search.captions"] = [{"text": c} for c in captions]
    return doc


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr("tacit.search_store.build_credential", lambda *a, **k: object())
    settings = Settings(
        project="demo",
        team="platform",
        search_endpoint="https://srch-x.search.windows.net",
    )
    store = SearchStore(settings, credential=object())
    fake = FakeSearch()
    store._post = fake  # type: ignore[method-assign]
    store.fake = fake  # type: ignore[attr-defined]
    return store


def _memory(
    content: str,
    path: str = "/runbooks/oncall.md",
    status=MemoryStatus.ACTIVE,
    project: str = "demo",
    visibility=Visibility.ORG,
):
    return Memory(
        path=path,
        content=content,
        project=project,
        team="platform",
        visibility=visibility,
        category="runbooks",
        tags=["oncall"],
        status=status,
        created_by="alice",
        updated_by="alice",
    )


def _version(path: str = "/runbooks/oncall.md", project: str = "demo"):
    return MemoryVersion(
        path=path,
        project=project,
        version=1,
        operation="create",
        content="# Oncall",
        content_sha256="abc",
        actor="alice",
        timestamp=utcnow(),
    )


def test_the_index_set_is_shared_by_the_whole_organization():
    """One index set, not one per project — that is what lets a search cross a
    team boundary, and what keeps a Basic service under its 15-index cap."""
    assert index_names() == ("tacit-memories", "tacit-versions", "tacit-chunks")


def test_put_projects_each_section_into_the_chunks_index(store):
    store.put(_memory("# Oncall\n\nlead\n\n## Failover\n\nPromote.\n\n## Refunds\n\nDrain."), _version())
    chunks = [b for i, s, b in store.fake.calls if i == "tacit-chunks" and s == "/docs/search.index"]
    assert len(chunks) == 1
    uploads = [a for a in chunks[0]["value"] if a["@search.action"] == "mergeOrUpload"]
    assert {a["section"] for a in uploads} == {"body", "failover", "refunds"}
    assert {a["key"] for a in uploads} == {
        "demo--runbooks--oncall-md--s-body",
        "demo--runbooks--oncall-md--s-failover",
        "demo--runbooks--oncall-md--s-refunds",
    }
    assert all(a["path"] == "/runbooks/oncall.md" for a in uploads)
    # Scope travels with every chunk, or a cross-project query could not filter.
    assert all(a["project"] == "demo" and a["visibility"] == "org" for a in uploads)


def test_chunk_keys_are_project_scoped_so_two_teams_cannot_collide(store):
    """Two projects may both keep /runbooks/oncall.md; in one shared index the
    keys must still differ or one team's write would erase the other's."""
    store.put(_memory("# Oncall\n\nlead", project="demo"), _version(project="demo"))
    store.put(_memory("# Oncall\n\nlead", project="other"), _version(project="other"))
    uploads = [
        a["key"]
        for i, s, b in store.fake.calls
        if i == "tacit-chunks" and s == "/docs/search.index"
        for a in b["value"]
        if a["@search.action"] == "mergeOrUpload"
    ]
    assert uploads == ["demo--runbooks--oncall-md--s-body", "other--runbooks--oncall-md--s-body"]


def test_stale_sections_are_deleted_on_update(store):
    """A heading that disappears must not linger as a searchable ghost."""
    store.fake.calls.clear()
    store._chunk_keys = lambda path: [  # type: ignore[method-assign]
        "demo--runbooks--oncall-md--s-body",
        "demo--runbooks--oncall-md--s-refunds",
    ]
    store.put(_memory("# Oncall\n\nlead only"), _version())
    actions = [b for i, s, b in store.fake.calls if i == "tacit-chunks"][0]["value"]
    deletes = [a["key"] for a in actions if a["@search.action"] == "delete"]
    uploads = [a["key"] for a in actions if a["@search.action"] == "mergeOrUpload"]
    assert deletes == ["demo--runbooks--oncall-md--s-refunds"]
    assert uploads == ["demo--runbooks--oncall-md--s-body"]


def test_deleted_memory_keeps_no_chunks(store):
    store._chunk_keys = lambda path: ["demo--runbooks--oncall-md--s-body"]  # type: ignore[method-assign]
    store.put(_memory("# Oncall\n\ngone", status=MemoryStatus.DELETED), _version())
    actions = [b for i, s, b in store.fake.calls if i == "tacit-chunks"][0]["value"]
    assert [a["@search.action"] for a in actions] == ["delete"]


def test_writes_and_single_memory_reads_never_leave_the_callers_project(store):
    """A store may only mutate and enumerate its own project; only search
    crosses the boundary."""
    store.list("/")
    store.versions("/runbooks/oncall.md")
    store.count()
    store._chunk_keys("/runbooks/oncall.md")
    filters = [b["filter"] for b in store.fake.bodies("/docs/search.post.search")]
    assert filters and all("project eq 'demo'" in f for f in filters)


def test_search_queries_chunks_with_semantic_and_projection(store):
    store.search("refund backlog", top=2)
    index, suffix, body = store.fake.calls[-1]
    assert index == "tacit-chunks"
    assert suffix == "/docs/search.post.search"
    assert body["queryType"] == "semantic"
    assert body["semanticConfiguration"] == SEMANTIC_CONFIG
    assert body["captions"].startswith("extractive")
    assert "select" in body and "content" in body["select"]
    assert "project" in body["select"], "a hit must say which team it came from"
    # Over-fetched: several sections of one memory can match and only the best
    # survives, so asking for exactly `top` would routinely return fewer.
    assert body["top"] > 2
    assert "scoringProfile" not in body, "the L2 reranker never sees BM25 scoring-profile order"


def test_semantic_rejection_falls_back_to_bm25_and_stays_down(store):
    store.fake.errors["semantic"] = RuntimeError(
        "HTTP 400: Semantic search is not enabled for this service"
    )
    hits = store.search("refund backlog")
    assert hits == []
    bodies = store.fake.bodies("/docs/search.post.search")
    assert bodies[0]["queryType"] == "semantic"
    assert "queryType" not in bodies[-1]
    assert bodies[-1]["scoringProfile"] == SCORING_PROFILE
    assert store._semantic_ok is False

    store.fake.calls.clear()
    store.search("second query")
    assert all("queryType" not in b for b in store.fake.bodies("/docs/search.post.search"))


def test_a_real_failure_is_not_swallowed_as_a_semantic_downgrade(store):
    store.fake.errors["search"] = RuntimeError("HTTP 503: service unavailable")
    with pytest.raises(RuntimeError, match="503"):
        store.search("anything")


def test_category_filter_and_versions_escape_odata_quotes():
    assert odata_quote("o'brien") == "o''brien"


def test_versions_filter_is_escaped(store):
    store.versions("/gotchas/o'brien.md")
    body = store.fake.bodies("/docs/search.post.search")[-1]
    assert "o''brien" in body["filter"]


def test_category_filter_is_escaped(store):
    store.search("q", category="it's")
    body = store.fake.bodies("/docs/search.post.search")[-1]
    assert body["filter"] == (
        "(project eq 'demo' or visibility eq 'org' or "
        "(visibility eq 'team' and team eq 'platform')) and category eq 'it''s'"
    )


def test_scope_filters_are_parenthesised_so_category_cannot_escape(store):
    """An unparenthesised OR chain would make `category` bind to the last
    disjunct only — silently returning other teams' memories of every category."""
    store.search("q", category="gotcha", scope=SearchScope.PROJECT)
    body = store.fake.bodies("/docs/search.post.search")[-1]
    assert body["filter"] == (
        "(project eq 'demo') and (project eq 'demo' or visibility eq 'org' or "
        "(visibility eq 'team' and team eq 'platform')) and category eq 'gotcha'"
    )


def test_org_scope_excludes_the_callers_own_project(store):
    """`org` answers 'what do other teams know that we don't' — including our
    own memories would drown that out with what we already have."""
    store.search("q", scope="org")
    body = store.fake.bodies("/docs/search.post.search")[-1]
    assert body["filter"].startswith("(not (project eq 'demo')")
    assert "visibility eq 'org'" in body["filter"]


def test_an_entity_filter_narrows_to_one_thing_in_the_shared_vocabulary(store):
    store.search("q", entity="payments-gateway")
    body = store.fake.bodies("/docs/search.post.search")[-1]
    assert "entities/any(e: e eq 'payments-gateway')" in body["filter"]


def test_chunks_carry_canonical_ids_and_every_alias(store):
    """Write-time normalization: the chunk must hold vocabulary its author
    never typed, or a question in another team's words cannot match it."""
    from tacit.ontology import Entity, Ontology

    store._ontology = Ontology(
        entities=[Entity(id="payments-gateway", name="Payments Gateway", aliases=("pmt-gw",))]
    )
    store.put(_memory("# pmt-gw drops connections\n\nRaise the timeout."), _version())
    upload = next(
        a
        for i, s, b in store.fake.calls
        if i == "tacit-chunks" and s == "/docs/search.index"
        for a in b["value"]
        if a["@search.action"] == "mergeOrUpload"
    )
    assert upload["entities"] == ["payments-gateway"]
    assert "Payments Gateway" in upload["entity_vocabulary"]


def test_the_vocabulary_participates_in_matching(store):
    """Aliases are only useful if the query is allowed to match them."""
    store.search("q")
    body = store.fake.bodies("/docs/search.post.search")[-1]
    assert "entity_vocabulary" in body["searchFields"]


def test_an_unreachable_vocabulary_degrades_instead_of_failing_writes(store):
    """Memory is useful without a vocabulary; a vocabulary outage must not
    block people from recording what they just learned."""
    store.fake.errors["*"] = RuntimeError("HTTP 500: ontology index exploded")
    store._ontology = None
    assert store.load_ontology().entities == []
    del store.fake.errors["*"]
    store.put(_memory("# Something\n\nx"), _version())
    upload = next(
        a
        for i, s, b in store.fake.calls
        if i == "tacit-chunks" and s == "/docs/search.index"
        for a in b["value"]
        if a["@search.action"] == "mergeOrUpload"
    )
    assert upload["entities"] == []


def test_saving_the_vocabulary_fails_closed_when_it_cannot_be_read(store):
    """Deletions are `existing - keep`. A swallowed read makes `existing` empty,
    emits no deletes, and silently turns a removal into a no-op — while still
    reporting success."""
    from tacit.ontology import Entity, Ontology

    store.fake.errors["*"] = RuntimeError("HTTP 503: transient")
    with pytest.raises(RuntimeError, match="503"):
        store.save_ontology(Ontology(entities=[Entity(id="a", name="A")]))


def test_removing_an_entity_emits_a_delete(store):
    from tacit.ontology import Entity, Ontology

    store.fake.responses = [{"value": [{"id": "gone", "name": "Gone"}]}]
    store.save_ontology(Ontology(entities=[Entity(id="kept", name="Kept")]))
    actions = [b for i, s, b in store.fake.calls if i == "tacit-ontology"
               and s == "/docs/search.index"][0]["value"]
    assert {"@search.action": "delete", "id": "gone"} in actions


def test_overfetch_never_exceeds_the_semantic_rerank_window(store):
    """Beyond 50 the service returns unreranked rows whose BM25 scores are on a
    different, unbounded scale — sorted together, the tail outranks the head."""
    from tacit.search_store import SEMANTIC_RERANK_WINDOW, _overfetch

    for top in (1, 3, 13, 25, 60, 5000):
        assert _overfetch(top) <= SEMANTIC_RERANK_WINDOW
    assert _overfetch(3) > 3, "still over-fetches enough to survive dedupe"


def test_top_is_clamped_before_it_reaches_the_service(store):
    from tacit.tools import MAX_SEARCH_TOP, call_tool

    captured = {}

    class Svc:
        project = "demo"

        def search(self, query, *, top, category, scope, entity):
            captured["top"] = top
            return []

    call_tool(Svc(), "memory_search", {"query": "x", "top": 100_000})
    assert captured["top"] == MAX_SEARCH_TOP


def test_list_pages_past_the_thousand_row_response_cap(store):
    """A project may hold more memories than one response returns, and reindex
    builds the chunks index from this — truncating leaves the remainder
    unsearchable."""
    stamp = "2026-01-01T00:00:00+00:00"

    def row(path):
        return {"path": path, "content": "# M", "project": "demo",
                "created": stamp, "updated": stamp}

    store.fake.responses = [
        {"value": [row(f"/m{i}.md") for i in range(1000)]},
        {"value": [row("/last.md")]},
    ]
    memories = store.list("/")
    assert len(memories) == 1001
    skips = [b.get("skip") for b in store.fake.bodies("/docs/search.post.search")]
    assert skips == [0, 1000]


def test_home_project_hits_are_boosted_over_equally_scored_neighbours(store):
    """Local knowledge wins ties, but the raw score is what the caller sees."""
    store.fake.responses = [
        {
            "value": [
                {**_doc("## R\n\nneighbour"), "project": "other", "@search.rerankerScore": 2.0},
                {**_doc("## R\n\nhome"), "project": "demo", "@search.rerankerScore": 2.0},
            ]
        }
    ]
    hits = store.search("refunds", top=2)
    assert [h.project for h in hits] == ["demo", "other"]
    assert hits[0].score == 2.0, "the boost orders results; it must not distort the score"


def test_a_strong_neighbour_still_outranks_a_weak_local_hit(store):
    """The home bias is a boost, not a hard sort key — otherwise another team's
    exact answer would always lose to our own vaguely related note."""
    store.fake.responses = [
        {
            "value": [
                {**_doc("## R\n\nneighbour"), "project": "other", "@search.rerankerScore": 9.0},
                {**_doc("## R\n\nhome"), "project": "demo", "@search.rerankerScore": 1.0},
            ]
        }
    ]
    assert [h.project for h in store.search("refunds", top=2)] == ["other", "demo"]


def test_only_the_best_section_of_each_memory_survives(store):
    """Same contract as the local backend: one hit per memory, best section."""
    store.fake.responses = [
        {
            "value": [
                {**_doc("## A\n\nrefunds"), "section": "a", "@search.rerankerScore": 1.0},
                {**_doc("## B\n\nrefunds again"), "section": "b", "@search.rerankerScore": 3.0},
            ]
        }
    ]
    hits = store.search("refunds", top=5)
    assert len(hits) == 1
    assert hits[0].section == "b"


def test_reindex_reprojects_every_memory(store, monkeypatch):
    memories = [_memory("# A\n\nx", path="/a.md"), _memory("# B\n\ny", path="/b.md")]
    monkeypatch.setattr(SearchStore, "list", lambda self, prefix="/": memories)
    synced: list[str] = []
    monkeypatch.setattr(SearchStore, "_sync_chunks", lambda self, m: synced.append(m.path))
    assert store.reindex() == 2
    assert synced == ["/a.md", "/b.md"]


class TestProgressiveDisclosure:
    """A hit carries the section, or — when the section is long — an extract of
    it plus ``truncated``. Never both: that would charge the caller twice for
    the same words."""

    def test_short_section_is_returned_whole_and_not_flagged(self, store):
        content = "## Refunds\n\nRaise REFUND_BATCH to 200; never add consumers."
        store.fake.responses = [{"value": [_doc(content, captions=["Raise REFUND_BATCH to 200."])]}]
        hit = store.search("refund batch")[0]
        assert hit.content == content
        assert hit.truncated is False

    def test_long_section_collapses_to_the_semantic_caption(self, store):
        content = "## Refunds\n\n" + ("padding sentence. " * 60) + "Raise REFUND_BATCH to 200."
        store.fake.responses = [{"value": [_doc(content, captions=["Raise REFUND_BATCH to 200."])]}]
        hit = store.search("refund batch")[0]
        assert hit.content == "Raise REFUND_BATCH to 200."
        assert hit.truncated is True
        assert len(hit.content) < len(content)

    def test_a_long_section_with_no_usable_extract_is_returned_whole(self, store):
        """Better a big honest answer than a truncated one that answers nothing."""
        content = "## Refunds\n\n" + ("padding sentence. " * 60)
        store.fake.responses = [{"value": [_doc(content, captions=[content])]}]
        hit = store.search("refund")[0]
        assert hit.truncated is False
        assert hit.content == content

    def test_highlights_stand_in_when_there_is_no_caption(self):
        doc = {"content": "body text", "@search.highlights": {"content": ["Raise REFUND_BATCH"]}}
        assert _extract_from(doc, "refund") == "Raise REFUND_BATCH"

    def test_local_extract_is_the_last_resort(self):
        content = ("padding sentence. " * 30) + "the refund worker is single-consumer. " + (
            "trailing. " * 30
        )
        extract = _extract_from({"content": content}, "refund worker single-consumer")
        assert "refund worker" in extract
        assert len(extract) < len(content)
