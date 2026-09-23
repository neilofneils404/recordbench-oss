"""Synthetic evaluation accounting and provenance, with no model/network access."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import socket

import pytest

from case_intelligence import claim_evaluation as evaluation
from case_intelligence import generation


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("R1b regressions must never contact a model or network.")
    monkeypatch.setattr(generation.urllib.request, "urlopen", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


@pytest.fixture
def runtime():
    return {"runtime_name": "synthetic", "runtime_version": "test-only",
            "accelerator": "none", "accelerator_memory_gib": 0, "driver": "none",
            "model_artifact_sha256": "a" * 64, "offline_readiness": "not_exercised",
            "offline_evidence_sha256": None,
            "upstream_model_id": "Qwen/Qwen3.5-4B",
            "upstream_revision": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a", "license": "Apache-2.0"}


class SyntheticClient:
    model = "synthetic-test-only"

    def generate(self, *, question, evidence):
        return {"answerable": True, "claims": [
            {"text": evidence[0].excerpt, "evidence_ids": ["S1"]},
            {"text": "An invented shuttle orbited Neptune.", "evidence_ids": ["S1"]},
        ], "limitation": {"text": evidence[0].excerpt, "evidence_ids": ["S1"]},
            "missing_information": ""}


def make_capture(runtime, client=None, repetitions=1, identity_check=lambda: None):
    return evaluation.capture(client or SyntheticClient(), profile="portable", runtime=runtime,
                              repetitions=repetitions, identity_check=identity_check)


def completed_grades(receipt):
    grades = evaluation.grade_template(receipt)
    grades["grader_id"] = "synthetic-grader"
    for sample in grades["samples"]:
        sample.update(answer_correct=False, rationale="Synthetic partial answer with fabricated claim.")
        for claim in sample["claims"]:
            claim.update(semantic_valid=claim["slot"] != "claim-1", citations_valid=True,
                         rationale="Synthetic ground truth independent of verifier.")
    return grades


def test_frozen_probes_measure_known_verifier_gaps_without_claiming_model_quality():
    receipt = evaluation.run_probes()
    evaluation.validate_receipt(receipt)
    assert len(receipt["results"]) == 27
    assert receipt["generation"] == {"status": "not_measured_injected_outputs", "model_calls": 0}
    assert all(row["execution"] == "not_exercised" for row in receipt["models"]["components"])
    for path, fa, fr in (("ordinary", 8, 0), ("exact_span", 1, 4)):
        assert receipt["verifier"][path]["false_acceptance"] == evaluation.fraction(fa, 14)
        assert receipt["verifier"][path]["false_rejection"] == evaluation.fraction(fr, 13)
    assert receipt["release_acceptance"].startswith("pending")
    cases = evaluation.load_suite()["cases"]
    assert len(cases) == len({case["case_id"] for case in cases}) == 11
    hashes = evaluation.load_suite()["source_text_sha256"]
    for case in cases:
        assert len(case["candidates"]) == len({row["candidate_id"] for row in case["candidates"]})
        for item in case["evidence"]:
            assert hashlib.sha256(item["excerpt"].encode()).hexdigest() == hashes[item["document_id"]]


def test_suite_rubric_changes_fail_frozen_fingerprint(monkeypatch, tmp_path):
    suite = evaluation.load_suite()
    suite["rubric"]["thresholds"]["release_acceptance"] = "changed"
    path = tmp_path / "modified.json"
    path.write_text(json.dumps(suite))
    monkeypatch.setattr(evaluation, "SUITE_PATH", path)
    with pytest.raises(ValueError, match="Frozen"):
        evaluation.run_probes()


def test_raw_claims_limitations_and_repetitions_keep_separate_denominators(runtime):
    receipt = make_capture(runtime, repetitions=2)
    assert receipt["generation"] == {"status": "requires_independent_human_grading",
        "attempts": 22, "generated": 22, "schema_invalid": 0, "abstained": 0}
    assert len({row["sample_id"] for row in receipt["results"]}) == 22
    result = evaluation.score_capture(receipt, completed_grades(receipt))
    assert result["generation"]["semantic_claim_errors"] == evaluation.fraction(22, 66)
    assert result["generation"]["answer_error_among_generated"] == evaluation.fraction(22, 22)
    assert result["generation"]["failed_attempts"] == evaluation.fraction(0, 22)
    assert result["verifier"]["ordinary"]["false_acceptance"]["denominator"] == 22
    assert result["verifier"]["ordinary"]["false_rejection"]["denominator"] == 44


@pytest.mark.parametrize("mutation", ["stale_capture", "stale_rubric", "missing_sample",
    "duplicate_sample", "extra_sample", "missing_claim", "duplicate_claim", "ungraded"])
def test_incomplete_stale_or_duplicate_grades_cannot_shrink_denominators(runtime, mutation):
    receipt = make_capture(runtime)
    grades = completed_grades(receipt)
    if mutation == "stale_capture":
        grades["capture_sha256"] = "b" * 64
    elif mutation == "stale_rubric":
        grades["rubric_sha256"] = "b" * 64
    elif mutation == "missing_sample":
        grades["samples"].pop()
    elif mutation == "duplicate_sample":
        grades["samples"][-1] = copy.deepcopy(grades["samples"][0])
    elif mutation == "extra_sample":
        grades["samples"].append(copy.deepcopy(grades["samples"][0]))
    elif mutation == "missing_claim":
        grades["samples"][0]["claims"].pop()
    elif mutation == "duplicate_claim":
        grades["samples"][0]["claims"][-1] = copy.deepcopy(grades["samples"][0]["claims"][0])
    else:
        grades["samples"][0]["claims"][0]["semantic_valid"] = None
    with pytest.raises(ValueError):
        evaluation.score_capture(receipt, grades)


def test_capture_tampering_is_refused(runtime):
    receipt = make_capture(runtime)
    receipt["results"][0]["raw"]["claims"].pop()
    with pytest.raises(ValueError, match="digest"):
        evaluation.grade_template(receipt)


@pytest.mark.parametrize("mutation", ["empty", "duplicate", "wrong_verdict", "missing_code", "wrong_schema", "wrong_counts"])
def test_resealed_incomplete_or_inconsistent_capture_is_refused(runtime, mutation):
    receipt = make_capture(runtime)
    receipt.pop("receipt_sha256")
    if mutation == "empty":
        receipt["results"] = []
    elif mutation == "duplicate":
        receipt["results"][-1] = copy.deepcopy(receipt["results"][0])
    elif mutation == "wrong_verdict":
        receipt["results"][0]["verification"]["claims"][0]["ordinary_accepted"] = False
    elif mutation == "missing_code":
        receipt["execution"]["implementation_sha256"] = {}
    elif mutation == "wrong_schema":
        receipt["results"][0]["schema_valid"] = False
    else:
        receipt["generation"]["generated"] = 0
    with pytest.raises(ValueError):
        evaluation.grade_template(evaluation.seal(receipt))


def test_wrong_declared_model_revision_refused_before_calls(runtime):
    runtime["upstream_revision"] = "b" * 40
    with pytest.raises(ValueError, match="provenance"):
        make_capture(runtime)


def test_response_rejection_blocks_candidate_acceptance_and_keeps_limitation():
    evidence = (generation.EvidenceItem("S1", "Synthetic.txt", "Line 1", "Team Orchid sent the valve."),)
    claim = {"text": evidence[0].excerpt, "evidence_ids": ["S1"]}
    raw = {"answerable": True, "claims": [claim], "limitation": None,
           "missing_information": "", "unexpected": True}
    result = evaluation.verify_output(raw, evidence)
    assert all(result["response"][path]["state"] == "rejected" for path in ("ordinary", "exact_span"))
    assert not result["claims"][0]["ordinary_accepted"]
    assert not result["claims"][0]["exact_span_accepted"]
    assert evaluation.claim_slots({"claims": None, "limitation": claim}) == [("limitation", claim)]


def test_unavailable_is_not_success_and_zero_denominators_are_null(runtime):
    class Unavailable(SyntheticClient):
        def generate(self, **kwargs):
            raise generation.GenerationUnavailable("Synthetic error not copied to receipt")
    events = []
    receipt = make_capture(runtime, Unavailable(), identity_check=lambda: events.append("check"))
    assert len(events) == 23  # before + after all 11 requests, then final check
    grades = evaluation.grade_template(receipt)
    grades["grader_id"] = "synthetic-grader"
    score = evaluation.score_capture(receipt, grades)
    assert score["generation"]["failed_attempts"] == evaluation.fraction(11, 11)
    assert score["generation"]["answer_error_among_generated"] == evaluation.fraction(0, 0)
    assert score["verifier"]["ordinary"]["false_acceptance"]["rate"] is None
    assert "Synthetic error" not in json.dumps(receipt)


def test_abstentions_and_malformed_slots_are_retained_and_need_grading(runtime):
    class Mixed(SyntheticClient):
        calls = 0
        def generate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"answerable": False, "claims": [], "limitation": None, "missing_information": ""}
            return {"answerable": True, "claims": [42], "limitation": None, "missing_information": ""}
    receipt = make_capture(runtime, Mixed())
    assert receipt["generation"]["schema_invalid"] == 10
    assert receipt["generation"]["abstained"] == 1
    grades = completed_grades(receipt)
    assert grades["samples"][0]["claims"] == []
    assert len(grades["samples"][1]["claims"]) == 1


@pytest.mark.parametrize("at", [1, 2, 3, 23])
def test_identity_failure_at_any_boundary_is_fatal(runtime, at):
    calls = 0
    def check():
        nonlocal calls
        calls += 1
        if calls == at:
            raise RuntimeError("Synthetic identity failure")
    with pytest.raises(RuntimeError, match="identity"):
        make_capture(runtime, identity_check=check)


def test_no_overwrite_and_no_model_grading_for_injected_output(tmp_path):
    path = tmp_path / "receipt.json"
    evaluation.write_new(path, {"retained": True})
    with pytest.raises(FileExistsError):
        evaluation.write_new(path, {})
    assert json.loads(path.read_text()) == {"retained": True}
    with pytest.raises(ValueError, match="real-model"):
        evaluation.grade_template(evaluation.run_probes())


def cli_module():
    path = Path(__file__).resolve().parents[1] / "scripts/evaluate-claims.py"
    spec = importlib.util.spec_from_file_location("r1b_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("backend", ["ollama", "openai"])
def test_runtime_checks_identity_with_explicit_snapshot_limitation(monkeypatch, backend):
    cli = cli_module()
    state = {"matches": True}
    def metadata(*args, **kwargs):
        if backend == "ollama":
            return {"models": [{"name": "synthetic", "digest": ("a" if state["matches"] else "b") * 64}]}
        return {"data": [{"id": "synthetic" if state["matches"] else "other"}]}
    monkeypatch.setattr(cli, "_bounded_json_get", metadata)
    _, check = cli.local_client(backend, "http://127.0.0.1:11435", "synthetic", "a" * 64)
    check()
    state["matches"] = False
    with pytest.raises(cli.IdentityError):
        check()


@pytest.mark.parametrize("endpoint", ["https://example.com", "http://127.0.0.1/path",
    "http://name:secret@127.0.0.1", "http://127.0.0.1?query=yes"])
def test_cli_rejects_nonisolated_or_credential_endpoints_before_calls(endpoint):
    with pytest.raises(ValueError):
        cli_module().local_client("ollama", endpoint, "synthetic", "a" * 64)


def test_cli_probe_path_is_network_free(tmp_path):
    path = tmp_path / "probes.json"
    assert cli_module().main(["probes", "--output", str(path)]) == 0
    assert json.loads(path.read_text())["generation"]["model_calls"] == 0


@pytest.mark.parametrize("backend", ["ollama", "openai"])
def test_cli_capture_uses_production_adapter_and_bound_grading(monkeypatch, tmp_path, runtime, backend):
    cli = cli_module()
    calls = []
    def metadata(*args, **kwargs):
        return {"models": [{"name": "synthetic", "digest": "a" * 64}],
                "data": [{"id": "synthetic"}]}
    def response(url, payload, **kwargs):
        calls.append(payload)
        content = json.dumps({"answerable": False, "claims": [],
                              "limitation": None, "missing_information": ""})
        return {"message": {"content": content}, "choices": [{"message": {"content": content}}]}
    monkeypatch.setattr(cli, "_bounded_json_get", metadata)
    monkeypatch.setattr(generation, "_bounded_json_request", response)
    profile = tmp_path / "runtime.json"
    profile.write_text(json.dumps(runtime))
    output = tmp_path / "capture.json"
    args = ["capture", "--backend", backend, "--endpoint", "http://127.0.0.1:11435",
            "--model", "synthetic", "--profile", "portable", "--repetitions", "1",
            "--runtime-profile", str(profile), "--output", str(output)]
    assert cli.main(args) == 0
    receipt = json.loads(output.read_text())
    evaluation.validate_receipt(receipt)
    assert len(calls) == len(receipt["results"]) == 11
    for payload, row in zip(calls, receipt["results"]):
        assert payload["messages"] == [{"role": role, "content": row["prompt"][role]}
                                       for role in ("system", "user")]
        if backend == "ollama":
            assert payload["options"]["num_predict"] == receipt["configuration"]["output_tokens"]
            assert payload["options"]["num_ctx"] == receipt["configuration"]["context_tokens"]
        else:
            assert payload["max_tokens"] == receipt["configuration"]["output_tokens"]
            assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    grades = completed_grades(receipt)
    score = evaluation.score_capture(receipt, grades)
    assert score["generation"]["answer_error_among_generated"] == evaluation.fraction(11, 11)
    with pytest.raises(SystemExit):
        cli.main(args)
    assert len(calls) == 11
