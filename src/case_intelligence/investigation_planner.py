"""Source-close search proposals. This planner has no tools or scope authority."""
from __future__ import annotations

import re
from typing import Mapping, Sequence

PLANNER_VERSION = 1
MAX_QUEUE = 40
# Prefer identifiers and dates, then quoted phrases and multi-word proper names.
_ANCHORS = (
    re.compile(r"\b[A-Za-z]{1,12}[-/]\d[A-Za-z0-9/-]{0,30}\b"),
    re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}\b"),
    re.compile(r'[“"]([^“”"\n]{3,80})[”"]'),
    re.compile(r"\b[A-Z][a-z]{2,}(?: [A-Z][a-z]{2,}){1,3}\b"),
)


def query_key(query: str) -> str:
    return " ".join(query.split()).casefold()


def initial_query(question: str) -> str:
    return " ".join(question.split())[:512].strip()


def validate_proposal(value: object, sources: Mapping[str, str]) -> dict | None:
    """Reject extra controls, fabricated anchors, and arbitrary query instructions."""
    if not isinstance(value, dict) or set(value) != {"query", "anchor", "reason", "support_token"}:
        return None
    if any(not isinstance(item, str) for item in value.values()):
        return None
    anchor = value["anchor"]
    excerpt = sources.get(value["support_token"], "")
    if not 3 <= len(anchor) <= 80 or anchor not in excerpt:
        return None
    if value["query"] != anchor or value["reason"] != "Follow a name, date, phrase, or identifier in this passage; look for corroborating or competing accounts.":
        return None
    return dict(value)


def propose_searches(evidence: Sequence[object], searched: Sequence[str], pending: Sequence[dict]) -> list[dict]:
    if len(pending) >= MAX_QUEUE:
        return []
    seen = {query_key(query) for query in searched}
    seen.update(query_key(item["query"]) for item in pending)
    proposals = []
    for citation in evidence:
        excerpt = citation.excerpt[:6000]
        for pattern in _ANCHORS:
            for match in pattern.finditer(excerpt):
                anchor = match.group(1) if match.lastindex else match.group()
                key = query_key(anchor)
                if key in seen:
                    continue
                value = {"query": anchor, "anchor": anchor,
                         "reason": "Follow a name, date, phrase, or identifier in this passage; look for corroborating or competing accounts.",
                         "support_token": citation.support_token}
                validated = validate_proposal(value, {citation.support_token: excerpt})
                if validated:
                    proposals.append(validated)
                    seen.add(key)
                if len(proposals) >= min(8, MAX_QUEUE - len(pending)):
                    return proposals
    return proposals
