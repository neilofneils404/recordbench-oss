"""Replaceable, local deterministic recognizer; suggestions are never identities.

This intentionally bounded recognizer is not general multilingual NER. It emits
original offsets, never transliterates OCR or infers speaker identity.
"""
from dataclasses import dataclass
import re
from typing import Iterable, Protocol


@dataclass(frozen=True)
class EntityOccurrence:
    start: int
    end: int
    label: str
    kind: str
    date: dict | None = None


class EntityExtractor(Protocol):
    version: str

    def extract(self, text: str) -> Iterable[EntityOccurrence]: ...


class DeterministicEntityExtractor:
    version = 'deterministic-entities-v1'
    # Unicode letters with uppercase initials; retain accents, apostrophes and
    # OCR digits. Sentence-start prose can still produce false positives.
    word = r"[^\W\d_][\w’'\-]*"
    labelled = re.compile(r'\b(person|name|witness|alias|organization|company|object)\s*:\s*([^;\n]{1,160})', re.I)
    identifiers = re.compile(r'\b(?:ID|VIN|serial|badge|plate|account|identifier)\s*[:#]\s*([\w-]{2,80})', re.I)
    dates = re.compile(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?\b')
    organization_ends = {'inc', 'llc', 'ltd', 'corp', 'company', 'association', 'university', 'cooperative', 'foundation', 'bank'}

    def extract(self, text):
        selected = {}
        labelled_spans = []
        priority = {'identifier': 0, 'thing': 1, 'organization': 2, 'person': 3, 'date': 4}
        def add(start, end, label, kind, date=None):
            key = (start, end)
            previous = selected.get(key)
            if previous is not None and priority[previous.kind] <= priority[kind]:
                return
            if previous is None and len(selected) >= 1000:
                raise ValueError('Entity proposal limit exceeded before materialization.')
            selected[key] = EntityOccurrence(start, end, label, kind, date)
        # Explicit rules run first and stop as soon as the bounded result set
        # fills. Do not build a million-object list merely to reject it later.
        for match in self.identifiers.finditer(text):
            add(match.start(1), match.end(1), match.group(1), 'identifier')
        for match in self.labelled.finditer(text):
            label = match.group(2).rstrip(' .\t\r')
            if label:
                start, end = match.start(2), match.start(2) + len(label)
                labelled_spans.append((start, end))
                add(start, end, label, 'organization' if match.group(1).casefold() in ('organization', 'company')
                    else 'thing' if match.group(1).casefold() == 'object' else 'person')
        token = re.compile(self.word, re.UNICODE)
        run = []
        last_end = None
        too_long = False
        def flush():
            nonlocal too_long, last_end
            if not too_long and 2 <= len(run) <= 5:
                start, end = run[0].start(), run[-1].end()
                if not any(left <= start and end <= right for left, right in labelled_spans):
                    add(start, end, text[start:end],
                        'organization' if run[-1].group().casefold() in self.organization_ends else 'person')
            run.clear()
            too_long = False
            last_end = None
        for match in token.finditer(text):
            value = match.group()
            if value[0].isupper() and value.casefold() not in {'id', 'vin', 'speaker', 'the', 'a', 'an', 'on', 'at', 'from', 'during'}:
                if last_end is not None and not re.fullmatch(r'[ \t]+', text[last_end:match.start()]):
                    flush()
                if len(run) < 5:
                    run.append(match)
                else:
                    too_long = True
                last_end = match.end()
            else:
                flush()
        flush()
        for match in self.dates.finditer(text):
            raw = match.group()
            zone = re.search(r'(Z|[+-]\d{2}:\d{2})$', raw)
            add(match.start(), match.end(), raw, 'date',
                dict(raw=raw, ambiguity='day/month order unresolved' if '/' in raw else 'calendar validity unverified',
                     timezone=zone.group() if zone else None, normalized=None))
        return sorted(selected.values(), key=lambda item: (item.start, item.end))
