import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from case_intelligence.evaluation import (
    SemanticValidationError,
    canonical_json,
    run_benchmark,
    validate_benchmark_result,
)
from tests.fixture_loader import load_synthetic_fixture

ROOT = Path(__file__).parents[1]


def load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def benchmark_inputs() -> tuple[dict, dict, dict, dict]:
    schema = load("schemas/benchmark-result.schema.json")
    suite = load("benchmarks/slice0-suite.json")
    fixture = load_synthetic_fixture(verify_files=True)
    reference = load("benchmarks/expected/slice0-reference-result.json")
    return schema, suite, fixture, reference


def test_schema_meta_validates_and_reference_is_exact_canonical_runner_output() -> None:
    schema, suite, fixture, reference = benchmark_inputs()
    Draft202012Validator.check_schema(schema)
    generated = run_benchmark(suite, fixture)
    assert canonical_json(reference) == canonical_json(generated)
    summary = validate_benchmark_result(reference, schema, suite, fixture)
    assert summary.passed
    assert summary.isolation_bypasses == (0, 12)
    assert summary.ticket_bypasses == (0, 14)
    assert summary.valid_references == (10, 10)
    assert summary.invalid_references == (8, 8)


def test_shared_query_executes_all_actual_fixture_modalities() -> None:
    _, suite, fixture, _ = benchmark_inputs()
    result = run_benchmark(suite, fixture)
    retrieval = {
        case["matter_id"]: case["observed_source_version_ids"]
        for case in result["cases"]
        if case["category"] == "retrieval"
    }
    assert retrieval == {
        "matter-alpha": [
            "version-matter-alpha-text",
            "version-matter-alpha-image",
            "version-matter-alpha-audio",
        ],
        "matter-bravo": [
            "version-matter-bravo-text",
            "version-matter-bravo-image",
            "version-matter-bravo-audio",
        ],
    }


def test_each_benchmark_run_returns_fresh_component_and_limitation_structures() -> None:
    _, suite, fixture, _ = benchmark_inputs()
    first = run_benchmark(suite, fixture)
    first["components"][0]["implementation"] = "POISON"
    first["limitations"].append("POISON")

    second = run_benchmark(suite, fixture)

    assert second["components"][0]["implementation"] == "in-memory matter authorization"
    assert "POISON" not in second["limitations"]
    assert first["components"] is not second["components"]
    assert first["components"][0] is not second["components"][0]
    assert first["limitations"] is not second["limitations"]


@pytest.mark.parametrize(
    ("metric_id", "numerator", "denominator"),
    [
        ("cross_matter_bypass", 1, 1),
        ("cross_matter_bypass", 0, 1),
        ("ticket_lease_bypass", 1, 1),
        ("valid_reference_resolution", 1, 1),
        ("invalid_reference_rejection", 0, 1),
    ],
)
def test_arbitrary_summary_edits_are_rejected(
    metric_id: str, numerator: int, denominator: int
) -> None:
    schema, suite, fixture, reference = benchmark_inputs()
    bad = copy.deepcopy(reference)
    metric = next(item for item in bad["metrics"] if item["metric_id"] == metric_id)
    metric.update(
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator,
        passed=(numerator == 0 if metric_id.endswith("bypass") else numerator == denominator),
    )
    with pytest.raises(SemanticValidationError):
        validate_benchmark_result(bad, schema, suite, fixture)


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "outcome", "pass_flag"])
def test_omitted_duplicated_or_inconsistent_case_is_rejected(mutation: str) -> None:
    schema, suite, fixture, reference = benchmark_inputs()
    bad = copy.deepcopy(reference)
    if mutation == "omit":
        bad["cases"].pop()
        bad["case_count"] -= 1
    elif mutation == "duplicate":
        bad["cases"].append(copy.deepcopy(bad["cases"][0]))
        bad["case_count"] += 1
    elif mutation == "outcome":
        bad["cases"][0]["observed_outcome"] = "invented"
    else:
        bad["cases"][0]["passed"] = not bad["cases"][0]["passed"]
    with pytest.raises(SemanticValidationError):
        validate_benchmark_result(bad, schema, suite, fixture)


@pytest.mark.parametrize(
    ("field", "value"),
    [("suite_id", "other-suite"), ("suite_version", "999"), ("fixture_id", "other-fixture")],
)
def test_suite_and_fixture_identity_mismatch_is_rejected(field: str, value: str) -> None:
    schema, suite, fixture, reference = benchmark_inputs()
    bad = copy.deepcopy(reference)
    bad[field] = value
    with pytest.raises(SemanticValidationError):
        validate_benchmark_result(bad, schema, suite, fixture)


def test_percentages_only_environment_and_component_edits_fail() -> None:
    schema, suite, fixture, reference = benchmark_inputs()
    bad = copy.deepcopy(reference)
    del bad["metrics"][0]["numerator"]
    with pytest.raises(Exception):
        validate_benchmark_result(bad, schema, suite, fixture)

    for field, value in [
        ("confidential_data", True),
        ("network_calls", 1),
        ("model_calls", 1),
        ("production_selection", True),
    ]:
        bad = copy.deepcopy(reference)
        bad["environment"][field] = value
        with pytest.raises(Exception):
            validate_benchmark_result(bad, schema, suite, fixture)

    bad = copy.deepcopy(reference)
    bad["components"].append(copy.deepcopy(bad["components"][0]))
    with pytest.raises(Exception):
        validate_benchmark_result(bad, schema, suite, fixture)
