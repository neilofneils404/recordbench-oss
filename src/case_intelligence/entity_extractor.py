"""Replaceable, local deterministic recognizer; suggestions are never identities.

This intentionally bounded recognizer is not general multilingual NER. It emits
original offsets, never transliterates OCR or infers speaker identity.
"""
from dataclasses import dataclass
import re
from typing import Protocol


@dataclass(frozen=True)
class EntityOccurrence:
    start: int
    end: int
    label: str
    kind: str
    date: dict | None = None


class EntityExtractor(Protocol):
    version: str

    def extract(self, text: str) -> list[EntityOccurrence]: ...


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
        found = []
        # Tokenize capitalized runs rather than normalizing distinct labels.
        token = re.compile(self.word, re.UNICODE)
        run = []
        def flush():
            if 2 <= len(run) <= 5:
                label = text[run[0].start():run[-1].end()]
                kind = 'organization' if run[-1].group().casefold() in self.organization_ends else 'person'
                found.append(EntityOccurrence(run[0].start(), run[-1].end(), label, kind))
            run.clear()
        for match in token.finditer(text):
            value = match.group()
            if value[0].isupper() and value.casefold() not in {'id', 'vin', 'speaker', 'the', 'a', 'an', 'on', 'at', 'from', 'during'}:
                if run and not re.fullmatch(r'[ \t]+', text[run[-1].end():match.start()]):
                    flush()
                run.append(match)
            else:
                flush()
        flush()
        for match in self.labelled.finditer(text):
            label = match.group(2).rstrip(' .\t\r')
            if label:
                start, end = match.start(2), match.start(2) + len(label)
                found = [item for item in found if not (start <= item.start and item.end <= end)]
                found.append(EntityOccurrence(start, end, label,
                    ('organization' if match.group(1).casefold() in ('organization', 'company')
                     else 'thing' if match.group(1).casefold() == 'object' else 'person')))
        for match in self.identifiers.finditer(text):
            found.append(EntityOccurrence(match.start(1), match.end(1), match.group(1), 'identifier'))
        for match in self.dates.finditer(text):
            raw = match.group()
            zone = re.search(r'(Z|[+-]\d{2}:\d{2})$', raw)
            found.append(EntityOccurrence(match.start(), match.end(), raw, 'date',
                dict(raw=raw, ambiguity='day/month order unresolved' if '/' in raw else 'calendar validity unverified',
                     timezone=zone.group() if zone else None, normalized=None)))
        return sorted(found, key=lambda item: (item.start, item.end, item.kind))
