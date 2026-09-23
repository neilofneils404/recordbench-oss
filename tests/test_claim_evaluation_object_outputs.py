"""Generated receipt rows retain JSON objects, matching production adapters."""
import copy
import json

import pytest

from case_intelligence import claim_evaluation as evaluation
from case_intelligence import generation
from tests.test_claim_evaluation import (
    SyntheticClient, completed_grades, make_capture, no_network, runtime,  # noqa: F401
)


NON_OBJECTS = [[], ["synthetic claim"], "synthetic scalar", 0, 1.5, True, None]


@pytest.mark.parametrize("raw", NON_OBJECTS)
def test_resealed_nonobject_generated_output_cannot_change_grading_denominators(runtime, raw):
    receipt = make_capture(runtime)
    grades = completed_grades(receipt)
    row = receipt["results"][0]
    evidence = tuple(generation.EvidenceItem(**item)
                     for item in evaluation.load_suite()["cases"][0]["evidence"])
    row.update(raw=copy.deepcopy(raw), verification=evaluation.verify_output(raw, evidence), schema_valid=False)
    receipt["generation"] = evaluation.generation_counts(receipt["results"])
    receipt.pop("receipt_sha256")
    receipt = evaluation.seal(receipt)
    grades["capture_sha256"] = receipt["receipt_sha256"]
    grades["samples"][0]["claims"] = []
    with pytest.raises(ValueError, match="JSON object"):
        evaluation.grade_template(receipt)
    with pytest.raises(ValueError, match="JSON object"):
        evaluation.score_capture(receipt, grades)


@pytest.mark.parametrize("raw", NON_OBJECTS)
def test_nondict_adapter_return_is_failed_attempt_with_observed_return(runtime, tmp_path, raw):
    class Nonobject(SyntheticClient):
        def generate(self, **kwargs):
            return copy.deepcopy(raw)

    events = []
    receipt = make_capture(runtime, Nonobject(), identity_check=lambda: events.append("checked"))
    assert len(events) == 23 and len(receipt["results"]) == 11
    assert receipt["generation"] == {"status": "requires_independent_human_grading",
        "attempts": 11, "generated": 0, "schema_invalid": 0, "abstained": 0}
    for row in receipt["results"]:
        assert row["state"] == "generation_failure"
        assert row["failure_type"] == "GenerationRejected"
        assert row["parsed_response_received"] is True
        assert not {"raw", "verification", "schema_valid"} & row.keys()
    assert receipt["models"]["components"][0]["execution"] == "parsed_responses_observed_not_inference_attestation"
    evaluation.validate_receipt(receipt)
    grades = evaluation.grade_template(receipt)
    assert grades["samples"] == []
    grades["grader_id"] = "synthetic-grader"
    score = evaluation.score_capture(receipt, grades)
    assert score["generation"]["failed_attempts"] == evaluation.fraction(11, 11)
    assert score["generation"]["answer_error_among_generated"] == evaluation.fraction(0, 0)
    path = tmp_path / "receipt.json"
    evaluation.write_new(path, receipt)
    assert json.loads(path.read_text()) == receipt


def capture_real_adapter(runtime, monkeypatch, backend, raw):
    calls = []

    def synthetic_response(*args, **kwargs):
        calls.append(True)
        message = {"content": json.dumps(raw)}
        return {"message": message} if backend == "ollama" else {"choices": [{"message": message}]}

    monkeypatch.setattr(generation, "_bounded_json_request", synthetic_response)
    if backend == "ollama":
        client = generation.OllamaGenerator("http://127.0.0.1:11435", "synthetic-test-only")
        snapshot = {"method": "ollama_tag_digest_snapshots", "model": client.model,
                    "artifact_sha256": runtime["model_artifact_sha256"]}
    else:
        client = generation.OpenAICompatibleGenerator("http://127.0.0.1:11435", "synthetic-test-only",
                                                      disable_thinking=True)
        snapshot = {"method": "api_model_id_snapshots", "model": client.model, "artifact_sha256": None}
    events = []

    def identity():
        events.append(True)
        return snapshot

    receipt = evaluation.capture(client, profile="portable", runtime=runtime,
                                 repetitions=1, identity_check=identity)
    assert len(calls) == 11 and len(events) == 23
    return receipt


@pytest.mark.parametrize("backend", ["ollama", "openai"])
@pytest.mark.parametrize("raw", NON_OBJECTS)
def test_real_adapters_reject_nonobject_content_before_return(runtime, monkeypatch, backend, raw):
    receipt = capture_real_adapter(runtime, monkeypatch, backend, raw)
    assert receipt["generation"]["attempts"] == 11 and receipt["generation"]["generated"] == 0
    assert receipt["models"]["components"][0]["execution"] == "attempted_no_parsed_response"
    for row in receipt["results"]:
        assert row["state"] == "generation_failure" and row["failure_type"] == "GenerationUnavailable"
        assert row["parsed_response_received"] is False
        assert not {"raw", "verification", "schema_valid"} & row.keys()
    evaluation.validate_receipt(receipt)
    assert evaluation.grade_template(receipt)["samples"] == []


@pytest.mark.parametrize("backend", ["ollama", "openai"])
def test_schema_invalid_object_still_retains_raw_output_for_grading(runtime, monkeypatch, backend):
    receipt = capture_real_adapter(runtime, monkeypatch, backend, {})
    assert receipt["generation"]["attempts"] == receipt["generation"]["generated"] == 11
    assert receipt["generation"]["schema_invalid"] == 11
    assert all(row["raw"] == {} and row["parsed_response_received"] is True for row in receipt["results"])
    evaluation.validate_receipt(receipt)
    assert len(evaluation.grade_template(receipt)["samples"]) == 11
