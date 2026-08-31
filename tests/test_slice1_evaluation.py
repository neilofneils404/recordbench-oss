from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from case_intelligence.evaluation import canonical_json
from case_intelligence.slice1_evaluation import (
    Slice1SemanticValidationError,
    run_slice1_benchmark,
    validate_slice1_result,
    validate_suite,
)

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks/slice1a-suite.json"
FIXTURE_ROOT = ROOT / "tests/fixtures/synthetic/slice1-intake/v1"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_slice1_reference_is_schema_valid_and_exact_executable_output():
    suite = _load(SUITE); fixture = _load(FIXTURE_ROOT / "manifest.json")
    schema = _load(ROOT / "schemas/slice1-result.schema.json")
    reference = _load(ROOT / "benchmarks/expected/slice1a-reference-result.json")
    Draft202012Validator.check_schema(schema)
    generated = run_slice1_benchmark(suite, fixture, FIXTURE_ROOT)
    assert generated["passed"] is True
    assert canonical_json(generated) == canonical_json(reference)
    metrics = validate_slice1_result(reference, schema, suite, fixture, FIXTURE_ROOT)
    assert metrics["successful_cross_matter_reads"] == (0, 3)
    assert metrics["unauthorized_requests_reaching_candidate_scoring"] == (0, 2)
    assert metrics["successful_ticket_authorization_or_replay_bypasses"] == (0, 3)
    assert metrics["staff_projections_containing_forbidden_fields"] == (0, 2)


@pytest.mark.parametrize("mutation", ["duplicate", "omit", "invent", "definition"])
def test_suite_rejects_duplicate_omitted_invented_and_tampered_cases(mutation):
    suite = _load(SUITE); fixture = _load(FIXTURE_ROOT / "manifest.json")
    if mutation == "duplicate": suite["cases"].append(copy.deepcopy(suite["cases"][0]))
    elif mutation == "omit": suite["cases"].pop()
    elif mutation == "invent": suite["cases"][0]["case_id"] = "invented"
    else: suite["cases"][0]["operation"] = "pretend_pass"
    with pytest.raises(Slice1SemanticValidationError):
        validate_suite(suite, fixture)


def test_result_tampering_is_recomputed_and_returned_structures_are_fresh():
    suite = _load(SUITE); fixture = _load(FIXTURE_ROOT / "manifest.json")
    schema = _load(ROOT / "schemas/slice1-result.schema.json")
    first = run_slice1_benchmark(suite, fixture, FIXTURE_ROOT)
    first["metrics"][0]["numerator"] = 999
    with pytest.raises(Exception):
        validate_slice1_result(first, schema, suite, fixture, FIXTURE_ROOT)
    second = run_slice1_benchmark(suite, fixture, FIXTURE_ROOT)
    assert second["metrics"][0]["numerator"] == 3
    assert second["cases"][0] is not first["cases"][0]
