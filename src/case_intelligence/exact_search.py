"""Versioned exact-search grammar and document-level reference semantics.

This is independent of ranked answer retrieval. Callers must authorize and scope
documents before evaluating them; a query does not grant access to a population.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Callable, Iterable

GRAMMAR_VERSION = "recordbench-exact-v1"
MAX_QUERY_CHARS = 512
MAX_QUERY_TOKENS = 128
MAX_QUERY_DEPTH = 16
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'"})
_UNSUPPORTED = re.compile(r"^(?:NEAR|WITHIN|ADJ|W/\d+|PRE/\d+)(?:/\d+)?$", re.I)


class QuerySyntaxError(ValueError):
    """Safe, content-free explanation with a zero-based source position."""

    def __init__(self, message: str, position: int) -> None:
        self.message = message
        self.position = position
        super().__init__(f"{message} (character {position + 1}).")


def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", text).casefold()).translate(_APOSTROPHES)


def tokenize_text(text: str, *, budget_check: Callable[[], None] | None = None) -> tuple[str, ...]:
    """NFC/casefold words; retain internal apostrophes and ASCII hyphens.

    Other punctuation separates words. No stemming or stop-word removal occurs.
    A phrase is consecutive tokens within one extracted unit, never across units.
    """
    normalized = _normalize_text(text)
    words: list[str] = []
    word: list[str] = []
    for index, char in enumerate(normalized):
        if budget_check is not None and index % 4096 == 0:
            budget_check()
        attached_mark = bool(word) and unicodedata.category(char).startswith("M")
        internal_joiner = (bool(word) and char in "'-" and index + 1 < len(normalized)
                           and normalized[index + 1].isalnum())
        if char.isalnum() or attached_mark or internal_joiner:
            word.append(char)
        elif word:
            words.append("".join(word))
            word = []
    if word:
        words.append("".join(word))
    return tuple(words)


@dataclass(frozen=True)
class Literal:
    words: tuple[str, ...]
    phrase: bool = False


@dataclass(frozen=True)
class Not:
    operand: Expression


@dataclass(frozen=True)
class And:
    operands: tuple[Expression, ...]


@dataclass(frozen=True)
class Or:
    operands: tuple[Expression, ...]


Expression = Literal | Not | And | Or


def _plan(node: Expression) -> dict[str, object]:
    if isinstance(node, Literal):
        return {"operator": "phrase" if node.phrase else "term", "words": list(node.words)}
    if isinstance(node, Not):
        return {"operator": "not", "operand": _plan(node.operand)}
    return {
        "operator": "and" if isinstance(node, And) else "or",
        "operands": [_plan(item) for item in node.operands],
    }


def _normalized(node: Expression, parent_precedence: int = 0) -> str:
    if isinstance(node, Literal):
        value = " ".join(node.words)
        return f'"{value}"' if node.phrase else value
    if isinstance(node, Not):
        precedence = 3
        value = f"NOT {_normalized(node.operand, precedence)}"
    else:
        precedence = 2 if isinstance(node, And) else 1
        operator = " " if isinstance(node, And) else " OR "
        value = operator.join(_normalized(item, precedence) for item in node.operands)
    return f"({value})" if precedence < parent_precedence else value


@dataclass(frozen=True)
class ParsedQuery:
    original: str
    expression: Expression
    grammar_version: str = GRAMMAR_VERSION

    @property
    def normalized(self) -> str:
        return _normalized(self.expression)

    def to_dict(self) -> dict[str, object]:
        """Serializable backend contract; this is not SQL or an executable query."""
        return {
            "grammar_version": self.grammar_version,
            "original": self.original,
            "normalized": self.normalized,
            "expression": _plan(self.expression),
        }

    def matches_units(self, units: Iterable[str], *, budget_check: Callable[[], None] | None = None) -> bool:
        """Reference matching for one eligible, already-authorized document.

        AND/OR/NOT apply to the entire document. Positive term/phrase occurrences
        may be in different units, but an individual phrase cannot span units.
        Empty/unextracted documents never count as matches, including under NOT.
        """
        literals: set[Literal] = set()

        def collect(node: Expression) -> None:
            if isinstance(node, Literal):
                literals.add(node)
            elif isinstance(node, Not):
                collect(node.operand)
            else:
                for child in node.operands:
                    collect(child)

        collect(self.expression)
        found: set[Literal] = set()
        has_text = False
        for unit in units:
            tokens = tokenize_text(unit, budget_check=budget_check)
            if not tokens:
                continue
            has_text = True
            words = set(tokens)
            for literal in literals - found:
                if budget_check is not None:
                    budget_check()
                if len(literal.words) == 1:
                    matched = literal.words[0] in words
                else:
                    width = len(literal.words)
                    matched = False
                    for index in range(len(tokens) - width + 1):
                        if budget_check is not None and index % 4096 == 0:
                            budget_check()
                        if tokens[index:index + width] == literal.words:
                            matched = True
                            break
                if matched:
                    found.add(literal)

        def evaluate(node: Expression) -> bool:
            if isinstance(node, Literal):
                return node in found
            if isinstance(node, Not):
                return not evaluate(node.operand)
            values = (evaluate(child) for child in node.operands)
            return all(values) if isinstance(node, And) else any(values)

        return has_text and evaluate(self.expression)


@dataclass(frozen=True)
class _Token:
    kind: str
    position: int
    literal: Literal | None = None


def _lex(query: str) -> tuple[_Token, ...]:
    result: list[_Token] = []
    index = 0
    while index < len(query):
        if query[index].isspace():
            index += 1
            continue
        start = index
        char = query[index]
        if char in "()":
            result.append(_Token(char, start))
            index += 1
        elif char == '"':
            index += 1
            value: list[str] = []
            while index < len(query) and query[index] != '"':
                if query[index] == "\\":
                    index += 1
                    if index >= len(query) or query[index] not in {'"', "\\"}:
                        raise QuerySyntaxError('Escape only a quote or backslash inside a phrase', index - 1)
                value.append(query[index])
                index += 1
            if index == len(query):
                raise QuerySyntaxError("Close the quoted phrase", start)
            index += 1
            words = tokenize_text("".join(value))
            if not words:
                raise QuerySyntaxError("A phrase needs at least one word", start)
            result.append(_Token("literal", start, Literal(words, phrase=True)))
            if index < len(query) and not query[index].isspace() and query[index] not in "()":
                raise QuerySyntaxError("Separate the phrase from the next term", index)
        else:
            while index < len(query) and not query[index].isspace() and query[index] not in '()"':
                index += 1
            value = query[start:index]
            if index < len(query) and query[index] == '"':
                raise QuerySyntaxError("Separate the term from the quoted phrase", index)
            if value.upper() in {"AND", "OR", "NOT"}:
                result.append(_Token(value.upper(), start))
            else:
                if _UNSUPPORTED.fullmatch(value):
                    raise QuerySyntaxError("Proximity operators are not supported yet", start)
                if any(mark in value for mark in "*?~:"):
                    raise QuerySyntaxError("Wildcards, fuzzy search, and field operators are not supported yet", start)
                normalized = _normalize_text(value)
                if tokenize_text(normalized) != (normalized,):
                    raise QuerySyntaxError("Use a word, a quoted phrase, or AND, OR, NOT and parentheses", start)
                result.append(_Token("literal", start, Literal((normalized,))))
        if len(result) > MAX_QUERY_TOKENS:
            raise QuerySyntaxError("Use fewer terms and operators", start)
    return tuple(result)


class _Parser:
    def __init__(self, tokens: tuple[_Token, ...], end: int) -> None:
        self.tokens = tokens
        self.index = 0
        self.end = end

    @property
    def kind(self) -> str:
        return self.tokens[self.index].kind if self.index < len(self.tokens) else "end"

    @property
    def position(self) -> int:
        return self.tokens[self.index].position if self.index < len(self.tokens) else self.end

    def disjunction(self, depth: int = 0) -> Expression:
        nodes = [self.conjunction(depth)]
        while self.kind == "OR":
            self.index += 1
            nodes.append(self.conjunction(depth))
        return nodes[0] if len(nodes) == 1 else Or(tuple(nodes))

    def conjunction(self, depth: int) -> Expression:
        nodes = [self.unary(depth)]
        while self.kind in {"AND", "NOT", "literal", "("}:
            if self.kind == "AND":
                self.index += 1
            nodes.append(self.unary(depth))
        return nodes[0] if len(nodes) == 1 else And(tuple(nodes))

    def unary(self, depth: int) -> Expression:
        if depth > MAX_QUERY_DEPTH:
            raise QuerySyntaxError("Use fewer nested parentheses or NOT operators", self.position)
        if self.kind == "NOT":
            self.index += 1
            return Not(self.unary(depth + 1))
        if self.kind == "(":
            start = self.position
            self.index += 1
            node = self.disjunction(depth + 1)
            if self.kind != ")":
                raise QuerySyntaxError("Close the parenthesized expression", start)
            self.index += 1
            return node
        if self.kind == "literal":
            token = self.tokens[self.index]
            self.index += 1
            assert token.literal is not None
            return token.literal
        raise QuerySyntaxError("Add a search term or phrase here", self.position)


def parse_query(query: str) -> ParsedQuery:
    if not isinstance(query, str):
        raise QuerySyntaxError("Enter a text query", 0)
    if len(query) > MAX_QUERY_CHARS:
        raise QuerySyntaxError(f"Keep the query within {MAX_QUERY_CHARS} characters", MAX_QUERY_CHARS)
    for index, char in enumerate(query):
        if unicodedata.category(char).startswith("C"):
            raise QuerySyntaxError("Remove control or hidden formatting characters", index)
    tokens = _lex(query)
    if not tokens:
        raise QuerySyntaxError("Enter a search term or phrase", 0)
    parser = _Parser(tokens, len(query))
    expression = parser.disjunction()
    if parser.kind != "end":
        raise QuerySyntaxError("Remove the unmatched closing parenthesis", parser.position)
    parsed = ParsedQuery(query, expression)
    if len(parsed.normalized) > MAX_QUERY_CHARS:
        raise QuerySyntaxError(
            f"Keep the normalized query within {MAX_QUERY_CHARS} characters", len(query)
        )
    return parsed
