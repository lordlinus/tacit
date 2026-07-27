"""SearchStore request shaping, with the network stubbed.

These pin the parts that only the Azure backend has: the derived chunks index,
the semantic-ranker downgrade, snippet economy, and OData escaping. They assert
on the request bodies we send, because a wrong body fails silently as bad
ranking rather than as an error.
"""

import pytest

from tacit.config import Settings
from tacit.models import Memory, MemoryStatus, MemoryVersion, utcnow
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
        backend="search",
        project="demo",
        search_endpoint="https://srch-x.search.windows.net",
    )
    store = SearchStore(settings, credential=object())
    fake = FakeSearch()
    store._post = fake  # type: ignore[method-assign]
    store.fake = fake  # type: ignore[attr-defined]
    return store


def _memory(content: str, path: str = "/runbooks/oncall.md", status=MemoryStatus.ACTIVE):
    return Memory(
        path=path,
        title="Oncall",
        content=content,
        category="runbooks",
        tags=["oncall"],
        status=status,
        created_by="alice",
        updated_by="alice",
    )


def _version(path: str = "/runbooks/oncall.md"):
    return MemoryVersion(
        path=path,
        version=1,
        operation="create",
        content="# Oncall",
        content_sha256="abc",
        actor="alice",
        timestamp=utcnow(),
    )


def test_index_names_include_the_chunks_index():
    assert index_names("demo") == ("tm-demo", "tm-demo-versions", "tm-demo-chunks")


def test_put_projects_each_section_into_the_chunks_index(store):
    store.put(_memory("# Oncall\n\nlead\n\n## Failover\n\nPromote.\n\n## Refunds\n\nDrain."), _version())
    chunks = [b for i, s, b in store.fake.calls if i == "tm-demo-chunks" and s == "/docs/search.index"]
    assert len(chunks) == 1
    uploads = [a for a in chunks[0]["value"] if a["@search.action"] == "mergeOrUpload"]
    assert {a["section"] for a in uploads} == {"body", "failover", "refunds"}
    assert {a["key"] for a in uploads} == {
        "runbooks--oncall-md--s-body",
        "runbooks--oncall-md--s-failover",
        "runbooks--oncall-md--s-refunds",
    }
    assert all(a["path"] == "/runbooks/oncall.md" for a in uploads)


def test_stale_sections_are_deleted_on_update(store):
    """A heading that disappears must not linger as a searchable ghost."""
    store.fake.responses = [
        {"value": []},  # get -> not used
        {"value": [{"key": "runbooks--oncall-md--s-body"}, {"key": "runbooks--oncall-md--s-refunds"}]},
    ]
    store.fake.calls.clear()
    store._chunk_keys = lambda path: [  # type: ignore[method-assign]
        "runbooks--oncall-md--s-body",
        "runbooks--oncall-md--s-refunds",
    ]
    store.put(_memory("# Oncall\n\nlead only"), _version())
    actions = [b for i, s, b in store.fake.calls if i == "tm-demo-chunks"][0]["value"]
    deletes = [a["key"] for a in actions if a["@search.action"] == "delete"]
    uploads = [a["key"] for a in actions if a["@search.action"] == "mergeOrUpload"]
    assert deletes == ["runbooks--oncall-md--s-refunds"]
    assert uploads == ["runbooks--oncall-md--s-body"]


def test_deleted_memory_keeps_no_chunks(store):
    store._chunk_keys = lambda path: ["runbooks--oncall-md--s-body"]  # type: ignore[method-assign]
    store.put(_memory("# Oncall\n\ngone", status=MemoryStatus.DELETED), _version())
    actions = [b for i, s, b in store.fake.calls if i == "tm-demo-chunks"][0]["value"]
    assert [a["@search.action"] for a in actions] == ["delete"]


def test_search_queries_chunks_with_semantic_and_projection(store):
    store.search("refund backlog", top=2)
    index, suffix, body = store.fake.calls[-1]
    assert index == "tm-demo-chunks"
    assert suffix == "/docs/search.post.search"
    assert body["queryType"] == "semantic"
    assert body["semanticConfiguration"] == SEMANTIC_CONFIG
    assert body["captions"].startswith("extractive")
    assert "select" in body and "content" in body["select"]
    assert body["top"] == 2
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
    assert body["filter"] == "category eq 'it''s'"


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
