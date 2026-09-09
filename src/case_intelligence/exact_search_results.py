"""Bounded, complete document enumeration over an authorized source population.

This reference service deliberately does not use ranked retrieval or a changing
PostgreSQL candidate index. No result is returned when a scan cannot complete.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import re
import time
from typing import Iterable, Protocol

from .exact_search import And, Literal, Not, Or, ParsedQuery, parse_query, tokenize_text
from .pilot_uploads import PilotDocument, PilotStore, PilotUnit


class ExactSearchUnavailable(ValueError):
    pass


class ExactSearchChanged(ExactSearchUnavailable):
    pass


def build_search_query(words: str = "", phrase: str = "", exclude: str = "") -> str:
    """Plain form fields are literal words, never implicit operator syntax."""
    included = tokenize_text(words)
    phrase_words = tokenize_text(phrase)
    excluded = tokenize_text(exclude)
    parts = [f'"{word}"' for word in included]
    if phrase_words:
        parts.append('"' + " ".join(phrase_words) + '"')
    if excluded:
        parts.append('NOT (' + ' OR '.join(f'"{word}"' for word in excluded) + ')')
    if not parts:
        raise ValueError("Enter a name, word, or phrase to find in your sources.")
    return " ".join(parts)


@dataclass(frozen=True)
class ExactDocumentResult:
    document_id: str
    source_token: str
    source_name: str
    source_version: str
    passages: tuple[PilotUnit, ...]
    matching_unit_count: int


@dataclass(frozen=True)
class ExactSearchPage:
    query: ParsedQuery
    items: tuple[ExactDocumentResult, ...]
    total: int
    eligible: int
    population: int
    exclusions: dict[str, int]
    page: int
    pages: int
    page_size: int
    fingerprint: str


@dataclass(frozen=True)
class ExactScanPolicy:
    """Product request budgets, independent of workstation hardware."""
    max_documents: int = 10_000
    max_characters: int = 10_000_000
    max_seconds: float = 5.0


class ExactSearchBackend(Protocol):
    """Future indexed adapters must preserve complete membership and grammar."""
    def search(self, documents: Iterable[PilotDocument], query: str, *,
               scope: tuple[str, ...], page: int = 1, page_size: int = 25,
               expected_fingerprint: str = "") -> ExactSearchPage: ...


@dataclass(frozen=True)
class ReferenceExactSearchBackend:
    policy: ExactScanPolicy = ExactScanPolicy()

    def search(self, documents: Iterable[PilotDocument], query: str, *,
               scope: tuple[str, ...], page: int = 1, page_size: int = 25,
               expected_fingerprint: str = "") -> ExactSearchPage:
        return search_documents(documents, query, scope=scope, page=page,
            page_size=page_size, expected_fingerprint=expected_fingerprint,
            max_documents=self.policy.max_documents,
            max_characters=self.policy.max_characters, max_seconds=self.policy.max_seconds)


def _positive_literals(query: ParsedQuery) -> tuple[Literal, ...]:
    result: list[Literal] = []

    def visit(node, negated=False):
        if isinstance(node, Literal):
            if not negated:
                result.append(node)
        elif isinstance(node, Not):
            visit(node.operand, not negated)
        elif isinstance(node, (And, Or)):
            for child in node.operands:
                visit(child, negated)

    visit(query.expression)
    return tuple(dict.fromkeys(result))


def passage_preview(unit: PilotUnit, query: ParsedQuery, limit: int = 600) -> dict[str, object]:
    """Display-only highlights; preserve original text and never emit HTML."""
    words = {word for literal in _positive_literals(query) for word in literal.words}
    hits = [match.span() for match in re.finditer(r"\w+(?:['’‘-]\w+)*", unit.text)
            if any(word in words for word in tokenize_text(match.group()))]
    start = max(0, hits[0][0] - 90) if hits else 0
    end = min(len(unit.text), start + limit)
    pieces: list[tuple[str, bool]] = []
    cursor = start
    if start:
        pieces.append(("…", False))
    for left, right in hits:
        if left < start or right > end:
            continue
        pieces.append((unit.text[cursor:left], False))
        pieces.append((unit.text[left:right], True))
        cursor = right
    pieces.append((unit.text[cursor:end], False))
    if end < len(unit.text):
        pieces.append(("…", False))
    return {"number": unit.number, "location": unit.location, "pieces": tuple(pieces)}


def search_documents(
    documents: Iterable[PilotDocument], query: str, *, scope: tuple[str, ...],
    page: int = 1, page_size: int = 25, expected_fingerprint: str = "",
    max_documents: int = 10_000, max_characters: int = 10_000_000,
    max_seconds: float = 5.0,
) -> ExactSearchPage:
    """Caller holds source mutation lock and applies authorization/scope first.

    Re-evaluate every page, rejecting a supplied fingerprint if source content,
    versions, state, names, membership, scope, or grammar changed. This detects
    changes between requests; it is not a stored or frozen search receipt.
    """
    parsed = parse_query(query)
    if page < 1 or page_size not in {25, 50, 100}:
        raise ValueError("Choose a positive page and a page size of 25, 50, or 100.")
    deadline = time.monotonic() + max_seconds
    characters = population = eligible = 0
    exclusions: Counter[str] = Counter()
    matches: list[ExactDocumentResult] = []
    versions: list[tuple[str, str]] = []
    positives = _positive_literals(parsed)

    def check_budget():
        if population > max_documents or characters > max_characters or time.monotonic() > deadline:
            raise ExactSearchUnavailable(
                "Exact search exceeded its scan budget. No exact total or partial results are shown. "
                "Choose a smaller collection or source set and search again."
            )

    for document in documents:
        population += 1
        check_budget()
        digest = hashlib.sha256(json.dumps([
            document.document_id, document.version_id, document.state, document.display_name,
        ], ensure_ascii=True).encode())
        if document.state != "ready":
            exclusions["Not ready"] += 1
            versions.append((document.document_id, digest.hexdigest()))
            continue
        # A source loader failure invalidates the scan instead of reporting zero.
        try:
            units = document.parsed_units()
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            raise ExactSearchUnavailable("A source could not be read. No exact total is available; retry after source preparation.") from exc
        has_text = False
        for unit in units:
            characters += len(unit.text)
            check_budget()
            digest.update(json.dumps([unit.number, unit.text, unit.location], ensure_ascii=True).encode())
            has_text = has_text or bool(tokenize_text(unit.text, budget_check=check_budget))
        versions.append((document.document_id, digest.hexdigest()))
        if not has_text:
            exclusions["No searchable text"] += 1
            continue
        eligible += 1
        if parsed.matches_units((unit.text for unit in units), budget_check=check_budget):
            matching_units = tuple(unit for unit in units if any(
                ParsedQuery("", literal).matches_units([unit.text], budget_check=check_budget) for literal in positives
            ))
            matches.append(ExactDocumentResult(
                document.document_id, PilotStore.action_token(document), document.display_name, document.version_id,
                matching_units[:3], len(matching_units),
            ))
        check_budget()
    fingerprint = hashlib.sha256(json.dumps(
        [parsed.to_dict(), scope, sorted(versions)], ensure_ascii=True, sort_keys=True,
    ).encode()).hexdigest()
    check_budget()
    if expected_fingerprint and fingerprint != expected_fingerprint:
        raise ExactSearchChanged("Sources or search scope changed. Run the search again to get current results.")
    matches.sort(key=lambda item: (item.source_name.casefold(), item.document_id))
    pages = max(1, math.ceil(len(matches) / page_size))
    selected_page = min(page, pages)
    start = (selected_page - 1) * page_size
    return ExactSearchPage(parsed, tuple(matches[start:start + page_size]), len(matches),
                           eligible, population, dict(exclusions), selected_page, pages,
                           page_size, fingerprint)
