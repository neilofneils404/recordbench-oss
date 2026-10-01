"""Find words inside one open source's extracted sections.

This searches only the document the reviewer has open. Matching is literal,
case-insensitive and tolerant of line breaks between words; it does not stem or
rank. A section without a match does not establish that the words are absent
from the original file: extraction can be partial.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from markupsafe import Markup, escape

MAX_FIND_CHARS = 240
MAX_FIND_SECTIONS = 200
# Per request: matches are counted one at a time and never retained, so a
# one-character query over a maximum-size section stays bounded.
MAX_FIND_MATCHES = 10_000
MAX_HIGHLIGHTS = 2_000
SNIPPET_CHARS = 60


@dataclass(frozen=True)
class FindSection:
    unit_index: int
    label: str
    count: int
    before: str
    match: str
    after: str


@dataclass(frozen=True)
class FindResult:
    query: str
    sections: tuple[FindSection, ...]
    total_matches: int
    truncated: bool
    matching_sections: int = 0
    counts_capped: bool = False


def find_pattern(query: str) -> re.Pattern[str] | None:
    words = " ".join((query or "").split())[:MAX_FIND_CHARS].split()
    if not words:
        return None
    return re.compile(r"\s+".join(re.escape(word) for word in words), re.IGNORECASE)


def section_label(document, unit, total: int) -> str:
    if document.media_type == "application/pdf":
        return f"Page {unit.number}"
    if document.media_type.endswith("wordprocessingml.document"):
        return f"Section {unit.number} of {total}"
    return str(unit.location or f"Section {unit.number}")


def find_in_source(document, query: str) -> FindResult | None:
    """Return per-section matches in reading order, bounded for display and work.

    Only each section's first match is kept. Counting stops at
    MAX_FIND_MATCHES; later sections are then only checked for a first match,
    so the number of matching sections stays exact.
    """
    pattern = find_pattern(query)
    if pattern is None:
        return None
    units = document.parsed_units() if document.state == "ready" else ()
    sections: list[FindSection] = []
    total = 0
    matching = 0
    capped = False
    for ordinal, unit in enumerate(units, 1):
        found = pattern.finditer(unit.text)
        first = next(found, None)
        if first is None:
            continue
        matching += 1
        count = 1
        if total + count >= MAX_FIND_MATCHES:
            capped = True
        else:
            for _ in found:
                count += 1
                if total + count >= MAX_FIND_MATCHES:
                    capped = True
                    break
        total += count
        if len(sections) >= MAX_FIND_SECTIONS:
            continue
        before = " ".join(unit.text[max(first.start() - SNIPPET_CHARS, 0):first.start()].split())
        after = " ".join(unit.text[first.end():first.end() + SNIPPET_CHARS].split())
        sections.append(FindSection(ordinal, section_label(document, unit, len(units)), count,
                                    before, " ".join(first.group(0).split()), after))
    return FindResult(" ".join(query.split())[:MAX_FIND_CHARS], tuple(sections), total,
                      matching > len(sections), matching, capped)


def highlight_find(text: str, query: str) -> Markup:
    """Escape text and wrap literal matches of the query in <mark>, at most MAX_HIGHLIGHTS."""
    pattern = find_pattern(query)
    if pattern is None:
        return escape(text)
    pieces: list[str] = []
    cursor = 0
    for marked, match in enumerate(pattern.finditer(text)):
        if marked >= MAX_HIGHLIGHTS:
            break
        pieces.append(str(escape(text[cursor:match.start()])))
        pieces.append(f"<mark>{escape(match.group(0))}</mark>")
        cursor = match.end()
    pieces.append(str(escape(text[cursor:])))
    return Markup("".join(pieces))
