"""Sections: the retrieval unit.

A memory is ``# Title`` followed by Markdown. Splitting on level-2 headings
gives addressable chunks, so search can point at the part of a long memory that
matched instead of returning the whole thing.

Splitting is adaptive: tacit's convention is one focused fact per memory, and
such a memory has no ``##`` headings at all — it stays a single section, so
short memories behave exactly as they did before sectioning existed.

Fenced code blocks are never treated as headings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_HEADING = re.compile(r"^##\s+(?P<heading>.+?)\s*#*\s*$")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

MAX_SLUG_CHARS = 48

FULL_SECTION_CHARS = 700
"""Sections at or under this length are returned whole: an extract of them
would not save enough to be worth the loss of context. Longer sections are
narrowed to an extract and flagged ``truncated``."""

SNIPPET_RATIO = 0.6
"""An extract must be at most this fraction of its section to be worth
substituting; otherwise the section is returned whole."""
BODY = "body"
"""Slug of the implicit first section: the title plus anything before the first
level-2 heading. For an unsectioned memory this is the whole content."""


@dataclass(frozen=True, slots=True)
class Section:
    slug: str
    heading: str
    text: str


def slugify(heading: str) -> str:
    slug = _SLUG_STRIP.sub("-", heading.strip().lower()).strip("-")
    if len(slug) > MAX_SLUG_CHARS:
        slug = slug[:MAX_SLUG_CHARS].rsplit("-", 1)[0]
    return slug or BODY


def split_sections(content: str) -> list[Section]:
    """Split content into the lead section plus one per level-2 heading."""
    sections: list[Section] = []
    heading = ""
    buffer: list[str] = []
    in_fence = False
    fence_marker = ""

    def flush() -> None:
        text = "\n".join(buffer).strip("\n")
        if not text:
            return
        slug = slugify(heading) if heading else BODY
        sections.append(Section(slug=_unique(slug, sections), heading=heading, text=text))

    for line in content.splitlines():
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence = False
        if not in_fence:
            match = _HEADING.match(line)
            if match:
                flush()
                heading = match.group("heading")
                buffer = [line]
                continue
        buffer.append(line)
    flush()
    return sections or [Section(slug=BODY, heading="", text=content.strip())]


def _unique(slug: str, existing: list[Section]) -> str:
    taken = {s.slug for s in existing}
    if slug not in taken:
        return slug
    counter = 2
    while f"{slug}-{counter}" in taken:
        counter += 1
    return f"{slug}-{counter}"


_WORD = re.compile(r"[a-z0-9]+")


def snippet(text: str, query: str, *, width: int = 320) -> str:
    """A short extract of ``text`` around the densest run of query terms.

    Used for the local backend and as the fallback when Azure AI Search returns
    no caption, so a hit always costs a snippet rather than a whole section.
    """
    flat = " ".join(text.split())
    if len(flat) <= width:
        return flat
    terms = {t for t in _WORD.findall(query.lower()) if len(t) > 2}
    if not terms:
        return flat[:width].rstrip() + " …"
    lowered = flat.lower()
    best_start, best_score = 0, -1
    step = max(width // 4, 1)
    for start in range(0, max(len(flat) - width, 0) + 1, step):
        window = lowered[start : start + width]
        score = sum(window.count(term) for term in terms)
        if score > best_score:
            best_start, best_score = start, score
    extract = flat[best_start : best_start + width].strip()
    prefix = "… " if best_start > 0 else ""
    suffix = " …" if best_start + width < len(flat) else ""
    return f"{prefix}{extract}{suffix}"


def narrow(section_text: str, extract: str) -> tuple[str, bool]:
    """Choose what a search hit should carry: the whole section, or an extract.

    Returns ``(text, truncated)``. A short section is returned whole — an
    extract of it saves too little to justify losing the surrounding context.
    A long section is replaced by ``extract`` only if that is materially
    shorter, and the caller is told to ``memory_read`` for the rest.
    """
    flat_section = " ".join(section_text.split())
    if len(flat_section) <= FULL_SECTION_CHARS:
        return section_text, False
    flat_extract = " ".join(extract.split())
    if flat_extract and len(flat_extract) <= len(flat_section) * SNIPPET_RATIO:
        return flat_extract, True
    return section_text, False
