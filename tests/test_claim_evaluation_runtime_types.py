"""Runtime declarations retain their JSON types across capture and grading."""
import copy
import json
import socket

import pytest

from case_intelligence import claim_evaluation as evaluation
from case_intelligence import generation


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Runtime type regressions must never contact a model or network.")
    monkeypatch.setattr(generation.urllib.request, "urlopen", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


@pytest.fixture
def runtime():
    model = evaluation.model_records("portable", generator_exercised=False)["components"][0]
    return {"runtime_name": "synthetic", "runtime_version": "test-only", "accelerator": "none",
        "accelerator_memory_gib": 0, "driver": "none", "model_artifact_sha256": "1" * 64,
        "offline_readiness": "operator_attested", "offline_evidence_sha256": "2" * 64,
        "upstream_model_id": model["model_id"], "upstream_revision": model["revision"],
        "license": model["license"]}


@pytest.fixture
def capture(monkeypatch):
    calls = []
    observations = []
    def response(*args, **kwargs):
        calls.append("synthetic-response")
        content = json.dumps({"answerable": False, "claims": [], "limitation": None,
                              "missing_information": "Synthetic abstention."})
        return {"message": {"content": content}, "choices": [{"message": {"content": content}}]}
    monkeypatch.setattr(generation, "_bounded_json_request", response)
    def run(runtime, backend="openai"):
        client = (generation.OllamaGenerator("http://127.0.0.1:11435", "synthetic-runtime-types")
                  if backend == "ollama" else generation.OpenAICompatibleGenerator(
                      "http://127.0.0.1:11435", "synthetic-runtime-types"))
        def snapshot():
            observations.append("synthetic-identity")
            return {"method": "ollama_tag_digest_snapshots" if backend == "ollama" else "api_model_id_snapshots",
                    "model": client.model,
                    "artifact_sha256": runtime["model_artifact_sha256"] if backend == "ollama" else None}
        return evaluation.capture(client, profile="portable", runtime=runtime, repetitions=1,
                                  identity_check=snapshot)
    return run, calls, observations


def completed_grades(receipt):
    grades = evaluation.grade_template(receipt)
    grades["grader_id"] = "synthetic-runtime-type-grader"
    for sample in grades["samples"]:
        sample.update(answer_correct=False, rationale="Synthetic abstention.")
    return grades


@pytest.mark.parametrize("field", ["model_artifact_sha256", "offline_evidence_sha256"])
@pytest.mark.parametrize("operation", ["capture", "grade_template", "score_capture"])
def test_numeric_digest_cannot_cross_capture_or_grading_boundary(runtime, capture, field, operation):
    run, calls, observations = capture
    if operation == "capture":
        runtime[field] = int("1" * 64)
        with pytest.raises(ValueError, match="SHA-256|digest"):
            run(runtime)
        assert calls == observations == []
        return
    receipt = run(runtime)
    grades = completed_grades(receipt)
    receipt.pop("receipt_sha256")
    receipt["runtime"][field] = int("1" * 64)
    receipt = evaluation.seal(receipt)
    grades["capture_sha256"] = receipt["receipt_sha256"]
    with pytest.raises(ValueError, match="SHA-256|digest"):
        if operation == "grade_template":
            evaluation.grade_template(receipt)
        else:
            evaluation.score_capture(receipt, grades)


@pytest.mark.parametrize("field", ["upstream_model_id", "upstream_revision", "license"])
@pytest.mark.parametrize("value", [None, 1])
def test_standalone_runtime_validation_enforces_upstream_string_types(runtime, field, value):
    # Capture already compares these values with the pinned model record. This
    # checks the standalone profile validator's documented type contract too.
    runtime[field] = value
    with pytest.raises(ValueError):
        evaluation.validate_runtime(runtime)


@pytest.mark.parametrize("value", [[], {}, 1, None, False])
def test_offline_readiness_has_controlled_string_enum_validation(runtime, value):
    runtime["offline_readiness"] = value
    with pytest.raises(ValueError, match="Offline readiness"):
        evaluation.validate_runtime(runtime)


@pytest.mark.parametrize("value", [True, False, -1, 100000.1, float("nan"), float("inf"), "0", None])
def test_accelerator_memory_keeps_finite_numeric_bounds(runtime, value):
    runtime["accelerator_memory_gib"] = value
    with pytest.raises(ValueError):
        evaluation.validate_runtime(runtime)


@pytest.mark.parametrize("field", ["model_artifact_sha256", "offline_evidence_sha256"])
@pytest.mark.parametrize("value", [True, None, [], "A" * 64, "1" * 63])
def test_digest_shape_remains_strict(runtime, field, value):
    runtime[field] = value
    with pytest.raises(ValueError):
        evaluation.validate_runtime(runtime)


@pytest.mark.parametrize("backend", ["openai", "ollama"])
@pytest.mark.parametrize("offline", ["not_exercised", "operator_attested"])
@pytest.mark.parametrize("memory", [0, 100000.0])
def test_valid_digit_only_hash_strings_and_runtime_boundaries_remain_gradable(runtime, capture, backend, offline, memory):
    run, calls, observations = capture
    runtime.update(offline_readiness=offline, accelerator_memory_gib=memory)
    if offline == "not_exercised":
        runtime["offline_evidence_sha256"] = None
    original = copy.deepcopy(runtime)
    receipt = run(runtime, backend)
    score = evaluation.score_capture(receipt, completed_grades(receipt))
    assert runtime == original
    assert type(receipt["runtime"]["model_artifact_sha256"]) is str
    assert receipt["runtime"]["basis"] == "operator_declared_not_independently_verified"
    assert len(calls) == 11 and len(observations) == 23
    assert score["generation"]["failed_attempts"] == evaluation.fraction(0, 11)
