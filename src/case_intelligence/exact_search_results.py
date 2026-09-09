"""Bounded, complete document enumeration over an authorized source population.

This reference service deliberately does not use ranked retrieval or a changing
PostgreSQL candidate index. No result is returned when a scan cannot complete.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import json
import math
import unicodedata
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
    passage_positions: tuple[int, ...]
    explanation: ParsedQuery
    previews: tuple[dict[str, object], ...] = ()


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


def passage_preview(unit: PilotUnit, query: ParsedQuery, limit: int = 600, *, budget_check=None) -> dict[str, object]:
    """Display-only highlights; preserve original text and never emit HTML."""
    # Track original spans while applying the same canonical tokenizer used by
    # matching. Combining marks belong to their word and punctuation separates
    # consecutive phrase tokens without changing the displayed source text.
    tokens = []
    word_start = None
    for index, char in enumerate(unit.text + " "):
        if budget_check is not None and index % 4096 == 0:
            budget_check()
        attached_mark = word_start is not None and unicodedata.category(char).startswith("M")
        joiner = (word_start is not None and char in "'’‘-" and index + 1 < len(unit.text)
                  and unit.text[index + 1].isalnum())
        if char.isalnum() or attached_mark or joiner:
            if word_start is None:
                word_start = index
        elif word_start is not None:
            for token in tokenize_text(unit.text[word_start:index], budget_check=budget_check):
                tokens.append((token, word_start, index))
            word_start = None
    hits = []
    for literal in _positive_literals(query):
        if budget_check is not None:
            budget_check()
        size = len(literal.words)
        for index in range(len(tokens) - size + 1):
            if budget_check is not None and index % 4096 == 0:
                budget_check()
            if tuple(item[0] for item in tokens[index:index + size]) == literal.words:
                hits.append((tokens[index][1], tokens[index + size - 1][2]))
    # Merge overlapping term/phrase spans so source text is rendered once.
    merged = []
    for index, (left, right) in enumerate(sorted(hits)):
        if budget_check is not None and index % 4096 == 0:
            budget_check()
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    hits = merged
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
    if budget_check is not None:
        budget_check()
    return {"number": unit.number, "location": unit.location, "start_ms": unit.start_ms, "pieces": tuple(pieces)}


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
            document.media_type, document.page_count,
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
        covered_pages = {unit.number for unit in units if unit.text.strip()}
        if document.media_type == "application/pdf" and (
            document.page_count <= 0 or len(covered_pages) != document.page_count
            or any(number < 1 or number > document.page_count for number in covered_pages)
        ):
            exclusions["Incomplete page coverage"] += 1
            continue
        eligible += 1
        positives = parsed.explain_units((unit.text for unit in units), budget_check=check_budget)
        if positives is not None:
            matching_units = []
            for position, unit in enumerate(units, 1):
                supported = tuple(literal for literal in positives if
                    ParsedQuery("", literal).matches_units([unit.text], budget_check=check_budget))
                if supported:
                    matching_units.append((position, unit, supported))
            # Give each positive part of the selected Boolean proof a chance
            # to explain the match before filling the three-unit preview cap.
            selected_units = {}
            for literal in positives:
                supporting = next((item for item in matching_units if literal in item[2]), None)
                if supporting is not None:
                    selected_units[supporting[0]] = supporting[1]
                if len(selected_units) == 3:
                    break
            for position, unit, _ in matching_units:
                if len(selected_units) == 3:
                    break
                selected_units[position] = unit
            matches.append(ExactDocumentResult(
                document.document_id, PilotStore.action_token(document), document.display_name, document.version_id,
                tuple(selected_units.values()), len(matching_units),
                tuple(selected_units),
                ParsedQuery("", And(positives), parsed.grammar_version),
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
    selected = tuple(replace(item, previews=tuple({
        **passage_preview(unit, item.explanation, budget_check=check_budget), "position": position,
    } for position, unit in zip(item.passage_positions, item.passages))) for item in matches[start:start + page_size])
    check_budget()
    return ExactSearchPage(parsed, selected, len(matches),
                           eligible, population, dict(exclusions), selected_page, pages,
                           page_size, fingerprint)
