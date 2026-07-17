"""Dream pipeline: dedupe, stale supersession, transcript mining, input immutability."""

import pytest

from teamlore.dream import dream, load_transcripts
from teamlore.local_store import LocalStore
from teamlore.service import MemoryService


@pytest.fixture
def stores(tmp_path):
    input_service = MemoryService(LocalStore(tmp_path / "in"), actor="alice")
    output_service = MemoryService(LocalStore(tmp_path / "out"), actor="dream")
    return input_service, output_service


def test_merges_near_duplicates_newest_wins(stores):
    input_service, output_service = stores
    a = input_service.create("/gotchas/retry-429.md", "# Retry on 429 errors\n\nOld advice: retry 3 times.", category="gotcha")
    input_service.create("/gotchas/retries-on-429.md", "# Retrying on 429 error\n\nNew advice: per-file backoff.", category="gotcha")
    report = dream(input_service, output_service)
    assert report.kept == 1
    assert report.merged == 1
    survivors = output_service.list("/")
    assert len(survivors) == 1
    assert "per-file backoff" in survivors[0].content  # newest content won
    # Input store untouched.
    assert len(input_service.list("/")) == 2
    assert input_service.read("/gotchas/retry-429.md").content_sha256 == a.content_sha256


def test_distinct_memories_all_kept(stores):
    input_service, output_service = stores
    input_service.create("/a.md", "# Deploy pipeline uses azd")
    input_service.create("/b.md", "# Search index schema is versioned")
    report = dream(input_service, output_service)
    assert report.kept == 2
    assert report.merged == 0
    assert len(output_service.list("/")) == 2


def test_mines_uncovered_insights_from_transcripts(stores):
    input_service, output_service = stores
    input_service.create("/gotchas/utf8.md", "# Windows consoles need UTF-8 stdout", category="gotcha")
    transcript = (
        "ran the tests\n"
        "LEARNED: the CI job named 'test' must never be renamed\n"
        "GOTCHA: Windows consoles need UTF-8 stdout\n"  # already covered -> skipped
    )
    report = dream(input_service, output_service, transcripts=[transcript])
    assert report.mined == 1
    mined = [m for m in output_service.list("/") if m.path.startswith("/dreamed/")]
    assert len(mined) == 1
    assert "never be renamed" in mined[0].content


def test_output_store_must_be_empty(stores):
    input_service, output_service = stores
    output_service.create("/existing.md", "# Existing")
    with pytest.raises(ValueError):
        dream(input_service, output_service)


def test_load_transcripts_formats(tmp_path):
    (tmp_path / "a.md").write_text("LEARNED: one\n", encoding="utf-8")
    (tmp_path / "b.jsonl").write_text(
        '{"role": "assistant", "content": "LEARNED: two"}\n{"bad json\n', encoding="utf-8"
    )
    texts = load_transcripts(tmp_path)
    assert len(texts) == 2
    assert "one" in texts[0] and "two" in texts[1]
