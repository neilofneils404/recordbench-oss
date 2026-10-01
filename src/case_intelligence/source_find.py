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
    """Return per-section matches in reading order, bounded for display."""
    pattern = find_pattern(query)
    if pattern is None:
        return None
    units = document.parsed_units() if document.state == "ready" else ()
    sections: list[FindSection] = []
    total = 0
    truncated = False
    for ordinal, unit in enumerate(units, 1):
        matches = list(pattern.finditer(unit.text))
        if not matches:
            continue
        total += len(matches)
        if len(sections) >= MAX_FIND_SECTIONS:
            truncated = True
            continue
        first = matches[0]
        before = " ".join(unit.text[max(first.start() - SNIPPET_CHARS, 0):first.start()].split())
        after = " ".join(unit.text[first.end():first.end() + SNIPPET_CHARS].split())
        sections.append(FindSection(ordinal, section_label(document, unit, len(units)), len(matches),
                                    before, " ".join(first.group(0).split()), after))
    return FindResult(" ".join(query.split())[:MAX_FIND_CHARS], tuple(sections), total, truncated)


def highlight_find(text: str, query: str) -> Markup:
    """Escape text and wrap each literal match of the query in <mark>."""
    pattern = find_pattern(query)
    if pattern is None:
        return escape(text)
    pieces: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        pieces.append(str(escape(text[cursor:match.start()])))
        pieces.append(f"<mark>{escape(match.group(0))}</mark>")
        cursor = match.end()
    pieces.append(str(escape(text[cursor:])))
    return Markup("".join(pieces))
