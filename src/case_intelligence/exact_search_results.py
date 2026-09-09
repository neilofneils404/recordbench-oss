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

from .exact_search import And, Literal, Not, Or, ParsedQuery, Proximity, match_positionals, matching_spans, parse_query, tokenize_text
from .media_evidence import format_timestamp
from .pilot_uploads import DOCX_MEDIA_TYPE, EMAIL_MEDIA_TYPES, SPREADSHEET_MEDIA_TYPES, PilotDocument, PilotStore, PilotUnit, is_media_type
from .unit_stream import UnitRecordLimit

_SECTION_MEDIA_TYPES = {DOCX_MEDIA_TYPE} | EMAIL_MEDIA_TYPES | SPREADSHEET_MEDIA_TYPES


class ExactSearchUnavailable(ValueError):
    pass


class ExactSearchChanged(ExactSearchUnavailable):
    pass


def build_search_query(words: str = "", phrase: str = "", exclude: str = "", *,
                       proximity_first: str = "", proximity_second: str = "",
                       proximity_gap: str = "5", proximity_order: str = "either") -> str:
    """Plain form fields are literal words, never implicit operator syntax."""
    included = tokenize_text(words)
    phrase_words = tokenize_text(phrase)
    excluded = tokenize_text(exclude)
    parts = [f'"{word}"' for word in included]
    if phrase_words:
        parts.append('"' + " ".join(phrase_words) + '"')
    if proximity_first.strip() or proximity_second.strip():
        first, second = tokenize_text(proximity_first), tokenize_text(proximity_second)
        if not first or not second:
            raise ValueError("Enter both details to find them close together.")
        if not str(proximity_gap).isascii() or not str(proximity_gap).isdecimal() or not 0 <= int(proximity_gap) <= 100:
            raise ValueError("Choose between 0 and 100 words between the two details.")
        if proximity_order not in {"either", "first"}:
            raise ValueError("Choose either order or first detail before second.")
        operator = "NEAR" if proximity_order == "either" else "BEFORE"
        parts.append(f'"{" ".join(first)}" {operator}/{int(proximity_gap)} "{" ".join(second)}"')
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
    media_type: str = ""


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
    max_serialized_characters: int = 128_000_000
    max_record_chars: int = 8_000_000


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
            max_characters=self.policy.max_characters, max_seconds=self.policy.max_seconds,
            max_serialized_characters=self.policy.max_serialized_characters,
            max_record_chars=self.policy.max_record_chars)


def _positive_literals(query: ParsedQuery) -> tuple[Literal | Proximity, ...]:
    result: list[Literal | Proximity] = []

    def visit(node, negated=False):
        if isinstance(node, (Literal, Proximity)):
            if not negated:
                result.append(node)
        elif isinstance(node, Not):
            visit(node.operand, not negated)
        elif isinstance(node, (And, Or)):
            for child in node.operands:
                visit(child, negated)

    visit(query.expression)
    return tuple(dict.fromkeys(result))


def _validate_unit(unit: PilotUnit) -> None:
    """Reject corrupt decoded locators inside the source-reading boundary."""
    if type(unit.number) is not int or unit.number < 1:
        raise ValueError('Invalid derived unit number')
    if not isinstance(unit.text, str) or not isinstance(unit.location_label, str):
        raise ValueError('Invalid derived unit text or location')
    if unit.excerpt_digest and unit.excerpt_digest != hashlib.sha256(unit.text.encode('utf-8')).hexdigest():
        raise ValueError('Invalid derived excerpt digest')
    # Transcript projections also store millisecond offsets in the legacy line
    # fields, so zero is valid there as well as in explicit media timestamps.
    for value, minimum in ((unit.line_start, 0), (unit.line_end, 0),
                           (unit.start_ms, 0), (unit.end_ms, 0)):
        if value is not None and (type(value) is not int or value < minimum):
            raise ValueError('Invalid derived unit locator')
    if unit.line_start is not None and unit.line_end is not None and unit.line_end < unit.line_start:
        raise ValueError('Invalid derived line range')


def _validate_media_locator(document: PilotDocument, unit: PilotUnit,
                            ordinal: int, previous_start: int) -> None:
    """Match the locator relationships required by install_media_transcript."""
    if (type(document.duration_ms) is not int or document.duration_ms < 0
            or unit.number != ordinal or unit.start_ms is None or unit.end_ms is None
            or unit.start_ms < previous_start or unit.end_ms <= unit.start_ms
            or unit.end_ms > document.duration_ms + 2000):
        raise ValueError('Invalid transcript locator relationships')


def passage_preview(unit: PilotUnit, query: ParsedQuery, limit: int = 600, *, media_type: str = "", budget_check=None) -> dict[str, object]:
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
    token_words = tuple(item[0] for item in tokens)
    for literal in _positive_literals(query):
        if budget_check is not None:
            budget_check()
        # A preview needs one explaining occurrence per positive condition,
        # not every repeated occurrence in the complete source unit.
        span = next(matching_spans(token_words, literal, budget_check=budget_check), None)
        if span is not None:
            start_token, end_token = span
            hits.append((tokens[start_token][1], tokens[end_token - 1][2]))
    explaining_hits = tuple(hits)
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
    # Share the text allowance across explaining conditions. A unit can hold
    # an early word and a distant proximity span; selecting the unit once must
    # not hide later conditions. Long spans retain both ends with an omission.
    windows = []
    if not hits:
        windows = [(0, min(len(unit.text), limit))]
    for left, right in explaining_hits:
        allowance = max(1, limit // len(explaining_hits))
        if right - left <= allowance:
            start = max(0, left - min(90, (allowance - (right - left)) // 2))
            windows.append((start, min(len(unit.text), start + allowance)))
        else:
            half = allowance // 2
            windows.extend(((left, left + half), (right - (allowance - half), right)))
    merged_windows = []
    for start, end in sorted(windows):
        if merged_windows and start <= merged_windows[-1][1]:
            merged_windows[-1] = (merged_windows[-1][0], max(end, merged_windows[-1][1]))
        else:
            merged_windows.append((start, end))
    windows = merged_windows
    pieces: list[tuple[str, bool]] = []
    for window_index, (start, end) in enumerate(windows):
        cursor = start
        if start or window_index:
            pieces.append(("…", False))
        for index, (left, right) in enumerate(hits):
            if budget_check is not None and index % 4096 == 0:
                budget_check()
            left, right = max(left, start), min(right, end)
            if left >= right:
                continue
            pieces.append((unit.text[cursor:left], False))
            pieces.append((unit.text[left:right], True))
            cursor = right
        pieces.append((unit.text[cursor:end], False))
    if windows[-1][1] < len(unit.text):
        pieces.append(("…", False))
    if budget_check is not None:
        budget_check()
    location = unit.location
    if unit.start_ms is not None:
        location = format_timestamp(unit.start_ms)
        if unit.end_ms is not None and unit.end_ms != unit.start_ms:
            location += "–" + format_timestamp(unit.end_ms)
    elif media_type == DOCX_MEDIA_TYPE and not unit.location_label and unit.line_start is None:
        location = f"Section {unit.number}"
    return {"number": unit.number, "location": location, "start_ms": unit.start_ms, "pieces": tuple(pieces)}


def search_documents(
    documents: Iterable[PilotDocument], query: str, *, scope: tuple[str, ...],
    page: int = 1, page_size: int = 25, expected_fingerprint: str = "",
    max_documents: int = 10_000, max_characters: int = 10_000_000,
    max_seconds: float = 5.0, max_serialized_characters: int = 128_000_000,
    max_record_chars: int = 8_000_000,
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
    characters = serialized_characters = population = eligible = 0
    exclusions: Counter[str] = Counter()
    matches: list[ExactDocumentResult] = []
    versions: list[tuple[str, str]] = []

    def budget_failure():
        return ExactSearchUnavailable(
            "Exact search exceeded its scan budget. No exact total or partial results are shown. "
            "Choose a smaller collection or source set and search again."
        )

    def check_budget():
        if (population > max_documents or characters > max_characters
                or serialized_characters > max_serialized_characters or time.monotonic() > deadline):
            raise budget_failure()

    def charge_read(count):
        nonlocal serialized_characters
        serialized_characters += count
        check_budget()

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
        units, has_text = [], False
        media, timed_media, previous_start = is_media_type(document.media_type), None, -1
        section_backed = document.media_type in _SECTION_MEDIA_TYPES
        try:
            if (document.media_type == 'application/pdf' or section_backed) and (
                    type(document.page_count) is not int or document.page_count < 0):
                raise ValueError('Invalid derived page count')
            for ordinal, unit in enumerate(document.iter_parsed_units(budget_check=check_budget,
                    read_check=charge_read, max_record_chars=max_record_chars), 1):
                _validate_unit(unit)
                if section_backed and unit.number != ordinal:
                    raise ValueError('Invalid derived section numbering')
                if media:
                    has_timestamps = unit.start_ms is not None or unit.end_ms is not None
                    if timed_media is None:
                        timed_media = has_timestamps
                    elif timed_media != has_timestamps:
                        raise ValueError('Mixed timed and untimed transcript locators')
                    if timed_media:
                        _validate_media_locator(document, unit, ordinal, previous_start)
                        previous_start = unit.start_ms
                characters += len(unit.text)
                check_budget()
                # Retain only admitted text. A later unit or malformed tail
                # invalidates the whole scan without exposing partial totals.
                units.append(unit)
                digest.update(json.dumps([unit.number, unit.text, unit.location,
                    unit.start_ms, unit.end_ms], ensure_ascii=True).encode())
                has_text = has_text or bool(tokenize_text(unit.text, budget_check=check_budget))
            if section_backed and len(units) != document.page_count:
                raise ValueError('Incomplete derived section coverage')
            if media and not units and document.page_count != 0:
                raise ValueError('Incomplete derived transcript coverage')
            if timed_media and (type(document.page_count) is not int or len(units) != document.page_count):
                raise ValueError('Incomplete derived transcript coverage')
        except ExactSearchUnavailable:
            raise
        except UnitRecordLimit as exc:
            raise budget_failure() from exc
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            raise ExactSearchUnavailable("A source could not be read. No exact total is available; retry after source preparation.") from exc
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
                supported = tuple(match_positionals(
                    tokenize_text(unit.text, budget_check=check_budget), positives, budget_check=check_budget))
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
                media_type=document.media_type,
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
        **passage_preview(unit, item.explanation, media_type=item.media_type, budget_check=check_budget), "position": position,
    } for position, unit in zip(item.passage_positions, item.passages))) for item in matches[start:start + page_size])
    check_budget()
    return ExactSearchPage(parsed, selected, len(matches),
                           eligible, population, dict(exclusions), selected_page, pages,
                           page_size, fingerprint)
