from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
import random

import pytest

from case_intelligence.exact_search import (
    GRAMMAR_VERSION,
    MAX_QUERY_CHARS,
    MAX_QUERY_DEPTH,
    QuerySyntaxError,
    parse_query,
)

CORPUS = Path(__file__).parent / "fixtures/synthetic/product-foundation/v1/corpus.json"


def test_frozen_product_corpus_and_known_document_results():
    raw = CORPUS.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == CORPUS.with_suffix(".sha256").read_text().split()[0]
    data = json.loads(raw)
    assert data["provenance"] == "synthetic" and data["confidential_data"] is False
    documents = data["documents"]
    assert len({item["document_id"] for item in documents}) == len(documents)
    for item in documents:
        for unit in item["units"]:
            assert hashlib.sha256(unit["text"].encode()).hexdigest() == unit["sha256"]
    eligible = [item for item in documents if item["matter_id"] == data["matter_id"] and item["state"] == "ready"]
    for case in data["exact_search_cases"]:
        query = parse_query(case["query"])
        actual = [item["document_id"] for item in eligible if query.matches_units(unit["text"] for unit in item["units"])]
        assert actual == case["expected_document_ids"], case["query"]
    assert data["backend_acceptance"]["postgres_route"].startswith("pending")


@pytest.mark.parametrize("terms", itertools.product((False, True), repeat=3))
def test_boolean_precedence_and_grouping_truth_tables(terms):
    red, blue, bicycle = terms
    text = "neutral " + " ".join(word for word, present in zip(("red", "blue", "bicycle"), terms) if present)
    expected = {
        "red OR blue AND bicycle": red or (blue and bicycle),
        "(red OR blue) AND bicycle": (red or blue) and bicycle,
        "red AND NOT blue": red and not blue,
        "NOT (red OR blue)": not (red or blue),
        "NOT NOT bicycle": bicycle,
        "red blue": red and blue,
        "red NOT bicycle": red and not bicycle,
        "NOT red OR bicycle": not red or bicycle,
    }
    for value, wanted in expected.items():
        assert parse_query(value).matches_units([text]) is wanted


def test_document_scope_searches_all_units_and_phrase_does_not_cross_boundary():
    assert parse_query("red AND bicycle").matches_units(["red", "bicycle"])
    assert not parse_query('"red bicycle"').matches_units(["red", "bicycle"])
    assert not parse_query("red NOT blue").matches_units(iter(["red"] + ["routine"] * 100 + ["blue"]))
    assert not parse_query("NOT red").matches_units([])
    assert not parse_query("NOT red").matches_units(["", "-- ..."])


@pytest.mark.parametrize("query,text,wanted", [
    ("O’NEIL", "o'neil", True),
    ("café", "CAFE\u0301", True),
    ("Straße", "STRASSE", True),
    ("हिंदी", "हिंदी", True),
    ('"हिंदी"', "ह द", False),
    ("İ", "i\u0307", True),
    ("İ", "I", False),
    ("I", "İ", False),
    ("\u0390", "\u03b9\u0308\u0301", True),
    ("RB-101", "Item rb-101.", True),
    ("RB-101", "Item rb 101.", False),
    ("bike", "bikes", False),
    ('"and"', "and", True),
    ('"red bicycle"', "RED, BICYCLE!", True),
    ('"red bicycle"', "red broken bicycle", False),
    ('"say \\"hello\\""', 'say "hello"', True),
])
def test_literal_normalization_and_phrase_rules(query, text, wanted):
    assert parse_query(query).matches_units([text]) is wanted


@pytest.mark.parametrize("query", [
    "", "   ", "AND red", "red OR", "red AND OR blue", "()", "red)",
    "(red", '"red', '""', '"..."', 'red"blue"', '"red"blue',
    "red*", "name:red", "red?", "red~", "red -blue", "red & blue",
    "red NEAR/3 blue", "red W/3 blue", "red PRE/3 blue", "red WITHIN blue",
    "red\x00blue", "red\u202eblue", '"red\\q"', "red/blue", "red\\blue",
    "(" * (MAX_QUERY_DEPTH + 1) + "red" + ")" * (MAX_QUERY_DEPTH + 1),
    "NOT " * (MAX_QUERY_DEPTH + 1) + "red",
    "a " * 129,
    "a" * (MAX_QUERY_CHARS + 1),
])
def test_malformed_unsupported_and_excessive_queries_are_explicit(query):
    with pytest.raises(QuerySyntaxError) as caught:
        parse_query(query)
    assert 0 <= caught.value.position <= len(query)
    assert "character" in str(caught.value)
    assert len(str(caught.value)) < 180


def test_errors_locate_the_problem_without_echoing_query_content():
    with pytest.raises(QuerySyntaxError) as caught:
        parse_query("sensitive-name AND")
    assert caught.value.position == len("sensitive-name AND")
    assert "sensitive-name" not in str(caught.value)


def test_serialized_plan_retains_original_and_version_and_roundtrips_meaning():
    query = parse_query(' RED or ("Blue bicycle" and NOT truck) ')
    plan = query.to_dict()
    assert plan["original"] == ' RED or ("Blue bicycle" and NOT truck) '
    assert plan["grammar_version"] == GRAMMAR_VERSION
    assert plan["expression"]["operator"] == "or"
    assert json.loads(json.dumps(plan)) == plan
    again = parse_query(query.normalized)
    for text in ["red truck", "blue bicycle", "blue bicycle truck", "neutral"]:
        assert again.matches_units([text]) == query.matches_units([text])


def test_bounded_arbitrary_input_never_recurses_unchecked_or_silently_crashes():
    rng = random.Random(19)
    alphabet = 'red AND OR NOT()"*?-:/\\\u202e'
    for _ in range(500):
        value = "".join(rng.choice(alphabet) for _ in range(rng.randrange(1, 180)))
        try:
            parsed = parse_query(value)
        except QuerySyntaxError:
            continue
        assert isinstance(parsed.matches_units(["red bicycle"]), bool)


@pytest.mark.parametrize("value", [
    "NOT " * MAX_QUERY_DEPTH + "red",
    "NOT " * (MAX_QUERY_DEPTH - 1) + "(red OR blue)",
    "(" * MAX_QUERY_DEPTH + "red blue" + ")" * MAX_QUERY_DEPTH,
    " ".join(["a"] * 128),
    "red AND (blue OR (bicycle AND NOT truck))",
])
def test_normalization_preserves_meaning_at_grammar_boundaries(value):
    original = parse_query(value)
    reparsed = parse_query(original.normalized)
    for terms in itertools.product((False, True), repeat=4):
        text = "neutral " + " ".join(word for word, present in zip(("red", "blue", "bicycle", "truck"), terms) if present)
        assert original.matches_units([text]) == reparsed.matches_units([text])


def test_casefold_expansion_obeys_the_canonical_character_limit():
    query = parse_query("ß" * (MAX_QUERY_CHARS // 2))
    assert parse_query(query.normalized).expression == query.expression
    with pytest.raises(QuerySyntaxError, match="normalized query"):
        parse_query("ß" * MAX_QUERY_CHARS)


def test_match_explanation_selects_a_true_boolean_proof():
    assert parse_query("(red AND bicycle) OR green").explain_units(["red", "green"])[0].words == ("green",)
    assert parse_query("NOT (NOT red AND blue)").explain_units(["red"])[0].words == ("red",)
    assert parse_query("NOT (red OR blue)").explain_units(["green"]) == ()
    assert parse_query("red AND bicycle").explain_units(["red"]) is None
