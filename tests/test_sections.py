"""Sectioning is the retrieval unit, so its edge cases are load-bearing:
an over-eager split fragments a memory, an under-eager one hands back a wall
of text."""

from tacit.sections import BODY, slugify, snippet, split_sections


def test_memory_without_headings_stays_one_section():
    """tacit's convention is one focused fact per memory; those must not be
    chopped up, or every hit would carry a fragment of a fact."""
    sections = split_sections("# VPN breaks DNS\n\nUse 1.1.1.1 while connected.")
    assert len(sections) == 1
    assert sections[0].slug == "body"
    assert sections[0].heading == ""
    assert sections[0].text.startswith("# VPN breaks DNS")


def test_headings_split_and_lead_text_is_kept():
    sections = split_sections(
        "# Runbook\n\nPreamble line.\n\n## First step\n\nDo this.\n\n## Second step\n\nDo that."
    )
    assert [s.slug for s in sections] == ["body", "first-step", "second-step"]
    assert "Preamble line." in sections[0].text
    assert sections[1].heading == "First step"
    assert sections[1].text.startswith("## First step")
    assert "Do that." not in sections[1].text


def test_hash_inside_fenced_code_is_not_a_heading():
    """A shell comment must never become a section boundary."""
    sections = split_sections(
        "# Deploy\n\n```bash\n## not a heading\naz webapp up\n```\n\n## Rollback\n\nSwap slots."
    )
    assert [s.slug for s in sections] == ["body", "rollback"]
    assert "az webapp up" in sections[0].text


def test_duplicate_headings_get_distinct_slugs():
    """Slugs become document keys, so collisions would silently drop content."""
    sections = split_sections("# T\n\n## Notes\n\nA\n\n## Notes\n\nB")
    slugs = [s.slug for s in sections]
    assert len(slugs) == len(set(slugs))
    assert "B" in sections[-1].text


def test_slugify_bounds_length_and_charset():
    assert slugify("Webhook signature failures (staging only!)") == "webhook-signature-failures-staging-only"
    assert slugify("x" * 200).isascii()
    assert len(slugify("word " * 60)) <= 48
    assert slugify("###") == BODY


def test_snippet_centres_on_the_query_terms():
    body = ("filler sentence. " * 40) + "The refund worker is single-consumer by design. " + (
        "trailing text. " * 40
    )
    extract = snippet(body, "refund worker single-consumer", width=120)
    assert "refund worker" in extract
    assert len(extract) < len(body)


def test_snippet_of_short_text_is_the_text():
    assert snippet("short body", "body", width=320).strip() == "short body"
