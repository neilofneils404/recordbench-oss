"""State-specific capture evidence cannot hide raw samples or parsed responses."""
import copy
import json

import pytest

from case_intelligence import claim_evaluation as evaluation
from case_intelligence import generation
from tests.test_claim_evaluation import (
    SyntheticClient, completed_grades, make_capture, no_network, runtime,  # noqa: F401
)


def reseal(receipt):
    receipt.pop("receipt_sha256")
    return evaluation.seal(receipt)


@pytest.mark.parametrize("retained", ["all", "raw", "verification", "schema_valid"])
def test_resealed_failure_cannot_hide_generated_fields_from_grading(runtime, retained):
    receipt = make_capture(runtime)
    row = receipt["results"][0]
    row.update(state="generation_failure", failure_type="GenerationRejected", parsed_response_received=True)
    for field in ("raw", "verification", "schema_valid"):
        if retained not in {"all", field}:
            row.pop(field)
    receipt["generation"] = evaluation.generation_counts(receipt["results"])
    receipt = reseal(receipt)
    with pytest.raises(ValueError):
        evaluation.grade_template(receipt)
    with pytest.raises(ValueError):
        evaluation.score_capture(receipt, {"grader_id": "synthetic", "samples": []})


class Unavailable(SyntheticClient):
    def generate(self, **kwargs):
        raise generation.GenerationUnavailable("Synthetic adapter failure; do not retain this text.")


@pytest.mark.parametrize("field,value", [
    ("failure_type", None), ("failure_type", "UnknownFailure"), ("failure_type", []),
    ("parsed_response_received", None), ("parsed_response_received", 0),
    ("parsed_response_received", 1), ("parsed_response_received", True),
    ("elapsed_ms", None), ("elapsed_ms", -1), ("elapsed_ms", True), ("elapsed_ms", 1.5),
])
def test_failure_rows_require_typed_unambiguous_evidence(runtime, field, value):
    receipt = make_capture(runtime, Unavailable())
    row = receipt["results"][0]
    if value is None:
        row.pop(field, None)
    else:
        row[field] = value
    with pytest.raises(ValueError):
        evaluation.grade_template(reseal(receipt))


@pytest.mark.parametrize("mutation", ["missing_raw", "missing_verification", "missing_schema", "schema_number",
    "false_parsed", "missing_parsed", "failure_type", "unknown_field", "nonfinite_raw"])
def test_generated_rows_reject_incomplete_or_contradictory_shapes(runtime, mutation):
    receipt = make_capture(runtime)
    row = receipt["results"][0]
    if mutation.startswith("missing_"):
        row.pop({"missing_raw": "raw", "missing_verification": "verification",
                 "missing_schema": "schema_valid", "missing_parsed": "parsed_response_received"}[mutation], None)
    elif mutation == "schema_number":
        row["schema_valid"] = 1
    elif mutation == "false_parsed":
        row["parsed_response_received"] = False
    elif mutation == "failure_type":
        row["failure_type"] = "GenerationRejected"
    elif mutation == "unknown_field":
        row["hidden_raw"] = copy.deepcopy(row["raw"])
    else:
        row["raw"]["hidden_number"] = float("nan")
        row["verification"] = evaluation.verify_output(row["raw"], tuple(
            generation.EvidenceItem(**item) for item in evaluation.load_suite()["cases"][0]["evidence"]))
        row["schema_valid"] = False
        receipt["generation"] = evaluation.generation_counts(receipt["results"])
    with pytest.raises(ValueError):
        evaluation.grade_template(reseal(receipt))


@pytest.mark.parametrize("mutation", ["results_object", "results_null", "row_list", "sample_list",
    "case_list", "state_list", "repetition_bool"])
def test_malformed_row_collection_fails_closed_with_value_error(runtime, mutation):
    receipt = make_capture(runtime)
    if mutation == "results_object":
        receipt["results"] = {"samples": receipt["results"]}
    elif mutation == "results_null":
        receipt["results"] = None
    elif mutation == "row_list":
        receipt["results"][0] = []
    else:
        field = {"sample_list": "sample_id", "case_list": "case_id",
                 "state_list": "state", "repetition_bool": "repetition"}[mutation]
        receipt["results"][0][field] = True if mutation == "repetition_bool" else []
    with pytest.raises(ValueError):
        evaluation.grade_template(reseal(receipt))


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), "\ud800", {1, 2}])
def test_unserializable_parsed_responses_keep_execution_evidence_without_invalid_raw(runtime, tmp_path, invalid):
    class ParsedInvalid(SyntheticClient):
        def generate(self, **kwargs):
            return {"answerable": False, "claims": [], "limitation": None,
                    "missing_information": "", "invalid": invalid}

    events = []
    receipt = make_capture(runtime, ParsedInvalid(), identity_check=lambda: events.append("checked"))
    assert len(events) == 23
    assert receipt["models"]["components"][0]["execution"] == "parsed_responses_observed_not_inference_attestation"
    assert receipt["generation"] == {"status": "requires_independent_human_grading",
        "attempts": 11, "generated": 0, "schema_invalid": 0, "abstained": 0}
    for row in receipt["results"]:
        assert row["state"] == "generation_failure" and row["failure_type"] == "GenerationRejected"
        assert row["parsed_response_received"] is True
        assert not {"raw", "verification", "schema_valid"} & row.keys()
    output = tmp_path / "capture.json"
    evaluation.write_new(output, receipt)
    assert json.loads(output.read_text()) == receipt
    evaluation.validate_receipt(receipt)
    grades = evaluation.grade_template(receipt)
    assert grades["samples"] == []
    grades["grader_id"] = "synthetic-grader"
    score = evaluation.score_capture(receipt, grades)
    assert score["generation"]["failed_attempts"] == evaluation.fraction(11, 11)
    assert score["generation"]["answer_error_among_generated"] == evaluation.fraction(0, 0)


def test_adapter_failures_do_not_claim_parsed_response_observation(runtime):
    receipt = make_capture(runtime, Unavailable())
    assert all(row["parsed_response_received"] is False for row in receipt["results"])
    assert receipt["models"]["components"][0]["execution"] == "attempted_no_parsed_response"
    assert "do not retain this text" not in json.dumps(receipt)
    evaluation.validate_receipt(receipt)


def test_mixed_failures_preserve_all_attempts_and_raw_claim_denominators(runtime):
    class Mixed(SyntheticClient):
        calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"invalid": float("nan")}
            if self.calls == 2:
                raise generation.GenerationUnavailable("Synthetic request failed.")
            return super().generate(**kwargs)

    receipt = make_capture(runtime, Mixed())
    assert len(receipt["results"]) == 11
    assert [row["parsed_response_received"] for row in receipt["results"]] == [True, False] + [True] * 9
    assert receipt["generation"]["attempts"] == 11 and receipt["generation"]["generated"] == 9
    grades = completed_grades(receipt)
    assert len(grades["samples"]) == 9
    assert sum(len(row["claims"]) for row in grades["samples"]) == 27
    score = evaluation.score_capture(receipt, grades)
    assert score["generation"]["failed_attempts"] == evaluation.fraction(2, 11)
    assert score["generation"]["answer_error_among_generated"] == evaluation.fraction(9, 9)
    assert score["generation"]["semantic_claim_errors"] == evaluation.fraction(9, 27)


@pytest.mark.parametrize("mutation", ["verdict_bool", "verdict_count", "attempt_count", "abstention_count"])
def test_resealed_verification_and_counters_require_json_types(runtime, mutation):
    receipt = make_capture(runtime)
    if mutation == "verdict_bool":
        verdict = receipt["results"][0]["verification"]["claims"][0]
        assert type(verdict["ordinary_accepted"]) is bool
        verdict["ordinary_accepted"] = int(verdict["ordinary_accepted"])
    elif mutation == "verdict_count":
        response = receipt["results"][0]["verification"]["response"]["ordinary"]
        response["retained_claims"] = float(response["retained_claims"])
    elif mutation == "attempt_count":
        receipt["generation"]["attempts"] = float(receipt["generation"]["attempts"])
    else:
        assert receipt["generation"]["abstained"] == 0
        receipt["generation"]["abstained"] = False
    with pytest.raises(ValueError):
        evaluation.grade_template(reseal(receipt))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "\ud800", {1, 2}])
def test_external_receipt_must_be_finite_utf8_json_before_digest_or_replay(runtime, value):
    receipt = make_capture(runtime)
    receipt["execution"]["os_release"] = value
    receipt["receipt_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="finite UTF-8 JSON"):
        evaluation.validate_receipt(receipt)


@pytest.mark.parametrize("value", [None, [], "receipt", 1, True])
def test_external_receipt_root_requires_json_object(value):
    with pytest.raises(ValueError, match="JSON object"):
        evaluation.validate_receipt(value)


def test_real_adapter_integer_parse_failure_retains_ten_prior_rows(runtime, monkeypatch, tmp_path):
    import sys

    calls = []
    limit = sys.get_int_max_str_digits()

    def synthetic_response(*args, **kwargs):
        calls.append(True)
        content = (json.dumps({"answerable": False, "claims": [], "limitation": None,
                              "missing_information": ""}) if len(calls) <= 10
                   else '{"extra":' + '1' * 5000 + '}')
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(generation, "_bounded_json_request", synthetic_response)
    client = generation.OpenAICompatibleGenerator("http://127.0.0.1:11435", "synthetic-test-only",
                                                  disable_thinking=True)
    events = []
    try:
        sys.set_int_max_str_digits(4300)
        receipt = make_capture(runtime, client, identity_check=lambda: events.append("checked"))
    finally:
        sys.set_int_max_str_digits(limit)
    assert len(calls) == 11 and len(events) == 23
    assert len(receipt["results"]) == 11
    assert [row["parsed_response_received"] for row in receipt["results"]] == [True] * 10 + [False]
    assert receipt["results"][-1]["failure_type"] == "GenerationRejected"
    assert not {"raw", "verification", "schema_valid"} & receipt["results"][-1].keys()
    assert receipt["generation"]["attempts"] == 11 and receipt["generation"]["generated"] == 10
    assert receipt["generation"]["abstained"] == 10
    assert receipt["models"]["components"][0]["execution"] == "parsed_responses_observed_not_inference_attestation"
    evaluation.validate_receipt(receipt)
    output = tmp_path / "capture.json"
    evaluation.write_new(output, receipt)
    assert json.loads(output.read_text()) == receipt
    grades = completed_grades(receipt)
    assert len(grades["samples"]) == 10
    assert evaluation.score_capture(receipt, grades)["generation"]["failed_attempts"] == evaluation.fraction(1, 11)


@pytest.mark.parametrize("where", ["generation_runtime", "identity_value"])
def test_data_failure_catch_does_not_swallow_fatal_boundary_errors(runtime, where):
    fatal = RuntimeError("Synthetic fatal transport boundary") if where == "generation_runtime" else ValueError(
        "Synthetic fatal identity boundary")

    class Boundary(SyntheticClient):
        def generate(self, **kwargs):
            if where == "generation_runtime":
                raise fatal
            return super().generate(**kwargs)

    def check():
        if where == "identity_value":
            raise fatal

    with pytest.raises(type(fatal)) as caught:
        make_capture(runtime, Boundary(), identity_check=check)
    assert caught.value is fatal
