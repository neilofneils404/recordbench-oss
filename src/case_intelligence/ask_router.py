"""Pure intent classification for a future shared Ask entry point.

Quotes, proximity and uppercase Boolean syntax win over enumeration. The input
must parse; malformed syntax falls through to ordinary intent classification.
This module selects a kind only and never executes a search or a model call.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal as Kind

from .exact_search import And, Expression, Literal, Not, Or, Proximity, QuerySyntaxError, parse_query


@dataclass(frozen=True)
class RouteDecision:
    kind: Kind["exact", "question", "every_source"]
    reason: str


# Consume complete quoted phrases and their escapes before matching operator tokens.
_BOOLEAN_OR_PHRASE = re.compile(r'"(?:[^"\\]|\\["\\])*"|(?<![^\s()])(?P<operator>AND|OR|NOT)(?![^\s()])')
# These are natural-language retrieval cues, not an exact-search grammar.
_FORMAT = r"\.?(?:pdf|docx|txt|jpg|jpeg|png|tif|tiff|eml|csv|tsv|xlsx|wav|mp3|m4a|ogg|opus|mp4|mov|webm)"
_RECORD = (
    r"(?:documents?|records?|sources?|files?|e-?mails?|messages?|texts?|reports?|"
    r"transcripts?|statements?|interviews?|recordings?|notes?|memos?|exhibits?|"
    r"attachments?|references?|mentions?|occurrences?|matches|results|evidence|items?|"
    rf"{_FORMAT}s?|videos?|images?|photos?|photographs?|pictures?|spreadsheets?|workbooks?|audio)"
)
_QUANTITY = r"(?:all(?:\s+of)?(?:\s+the)?|every(?:\s+single)?|each(?:\s+and\s+every)?)"
_MEDIA = rf"(?:{_FORMAT}|video|audio|image|photo|spreadsheet|text|excel|word)"
_POPULATION = (
    rf"{_QUANTITY}\s+(?:(?:matching|relevant|available)\s+)?"
    rf"(?:{_MEDIA}\s+)?{_RECORD}\b"
)
_RETRIEVE = (
    r"(?:find|list|show|locate|identify|retrieve|return|collect|get|check|review|"
    r"enumerate|search\s+for|give\s+me)"
)
_REQUEST = (
    r"(?:please\s+)?(?:(?:(?:can|could|would|will)\s+you|"
    r"i\s+(?:need|want)\s+(?:you\s+)?to)\s+(?:please\s+)?)?"
)
# Bare filtered populations are ambiguous subjects ("all records about X agree")
# as well as request fragments. Require a positive request cue for those forms.
_EVERY_SOURCE = re.compile(
    rf"^(?:{_REQUEST}{_RETRIEVE}\s+(?:me\s+)?"
    rf"(?:{_POPULATION}|{_QUANTITY}\s*[.!?]*$)"
    rf"|i\s+(?:need|want)\s+{_POPULATION}\s*[.!?]*$"
    rf"|(?:please\s+)?{_POPULATION}\s*[.!?]*$)",
    re.IGNORECASE,
)


def _exact_reason(node: Expression, *, uppercase_boolean: bool) -> str | None:
    if isinstance(node, Literal):
        return "Chose exact search because your words are in quotes." if node.phrase else None
    if isinstance(node, Proximity):
        return "Chose exact search because you specified how close words must be."
    if uppercase_boolean and (isinstance(node, (Not, Or)) or isinstance(node, And) and node.explicit):
        return "Chose exact search because you used a Boolean operator."
    operands = (node.operand,) if isinstance(node, Not) else node.operands
    for operand in operands:
        if reason := _exact_reason(operand, uppercase_boolean=uppercase_boolean):
            return reason
    return None


def classify(text: str) -> RouteDecision:
    """Choose a route without I/O or mutable state; exact intent requires valid grammar.

    Parse failures fall through to enumeration cues and otherwise remain questions.
    """
    text = text.strip()
    if not text:
        return RouteDecision("question", "Nothing was typed, so there is no question to answer yet.")

    try:
        parsed = parse_query(text)
    except QuerySyntaxError:
        pass
    else:
        uppercase = any(match["operator"] for match in _BOOLEAN_OR_PHRASE.finditer(text))
        if reason := _exact_reason(parsed.expression, uppercase_boolean=uppercase):
            return RouteDecision("exact", reason)

    if _EVERY_SOURCE.search(text):
        return RouteDecision("every_source", "Chose every source because you asked for all matching records.")
    return RouteDecision("question", "Chose a question because no search instructions were recognized.")
