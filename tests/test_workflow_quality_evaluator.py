"""Exercise the evaluator entrypoint with production grounding and synthetic transport."""
import importlib.util
import json
from pathlib import Path
import socket
import sys

import pytest

from case_intelligence import generation


DIGEST = "a" * 64
MODEL = "synthetic-cedar:review"


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def unexpected_network(*args, **kwargs):
        pytest.fail("Evaluator regressions must use synthetic transport, never network access.")

    monkeypatch.setattr(generation.urllib.request, "urlopen", unexpected_network)
    monkeypatch.setattr(socket, "create_connection", unexpected_network)
    monkeypatch.setattr(socket.socket, "connect", unexpected_network)
    monkeypatch.setattr(socket.socket, "connect_ex", unexpected_network)


@pytest.fixture
def evaluation(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts/evaluate-workflow-quality.py"
    spec = importlib.util.spec_from_file_location("cedar_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "receipt.json"
    monkeypatch.setattr(sys, "argv", [str(path), "--endpoint", "http://127.0.0.1:11435",
        "--model", MODEL, "--expected-digest", DIGEST, "--output", str(output)])
    state = {"digest": DIGEST, "requests": [], "events": [], "answer_calls": 0,
             "tag_reads": 0, "on_tag": lambda: None, "on_request": lambda: None,
             "on_metadata": lambda: None, "repair": False, "unavailable": False}

    def tags(*args, **kwargs):
        state["tag_reads"] += 1
        state["events"].append("tags")
        value = state.get("tags", {"models": [{"name": MODEL, "digest": state["digest"]}]})
        state["on_tag"]()
        return value

    def request(url, payload, **kwargs):
        assert url.endswith("/api/chat") and payload["model"] == MODEL
        classifier = "decision" in payload["format"]["properties"]
        state["requests"].append(("classify" if classifier else "answer", state["digest"]))
        state["events"].append("request")
        state["on_request"]()
        if state["unavailable"]:
            raise generation.GenerationUnavailable("Synthetic unavailable response.")
        if classifier:
            content = {"decision": "not_identified", "rationale": "No matching fact identified.", "evidence_ids": []}
        else:
            state["answer_calls"] += 1
            content = {"answerable": False, "claims": [], "limitation": None, "missing_information": ""}
            if state["repair"] and state["answer_calls"] == 1:
                content.update(answerable=True, claims=[{"text": "A fictional unsupported purchase order was issued.",
                    "evidence_ids": ["S99"]}])
        return {"message": {"content": json.dumps(content)}}

    def metadata(command, **kwargs):
        if command[1] == "status":
            state["on_metadata"]()
            return b""
        return "0" * 40 + "\n"

    monkeypatch.setattr(module, "_bounded_json_get", tags)
    monkeypatch.setattr(generation, "_bounded_json_get", tags)
    monkeypatch.setattr(generation, "_bounded_json_request", request)
    monkeypatch.setattr(module.subprocess, "check_output", metadata)
    return module, state, output


def assert_aborted(module, output):
    with pytest.raises((RuntimeError, SystemExit), match="(?i)(digest|identity)"):
        module.main()
    assert not output.exists()


@pytest.mark.parametrize("when", ["before_first_request", "during_classification", "between_requests",
    "during_answer", "before_repair", "during_repair", "before_receipt"])
def test_model_identity_change_aborts_without_misattributed_receipt(evaluation, when):
    module, state, output = evaluation
    if when == "before_first_request":
        def on_tag():
            if state["tag_reads"] == 2:
                state["digest"] = "b" * 64
        state["on_tag"] = on_tag
    elif when in {"between_requests", "before_repair"}:
        state["repair"] = when == "before_repair"
        def on_tag():
            if (len(state["requests"]) == 1 if when == "between_requests" else state["answer_calls"] == 1):
                state["digest"] = "b" * 64
        state["on_tag"] = on_tag
    elif when == "before_receipt":
        state["on_metadata"] = lambda: state.update(digest="b" * 64)
    else:
        state["repair"] = when == "during_repair"
        def on_request():
            if (when == "during_classification" or
                when == "during_answer" and state["requests"][-1][0] == "answer" or
                when == "during_repair" and state["answer_calls"] == 1):
                state["digest"] = "b" * 64
        state["on_request"] = on_request
    assert_aborted(module, output)
    if when == "before_first_request":
        assert state["requests"] == []
    elif when in {"during_classification", "between_requests"}:
        assert len(state["requests"]) == 1
    elif when == "before_repair":
        assert state["answer_calls"] == 1
    elif when == "during_repair":
        assert state["answer_calls"] == 2


@pytest.mark.parametrize("tags", [{}, {"models": []}, {"models": None},
    {"models": [{"name": MODEL, "digest": None}]},
    {"models": [{"name": MODEL, "digest": DIGEST}] * 2}])
def test_lost_or_ambiguous_identity_is_fatal_not_a_scored_unavailable_unit(evaluation, tags):
    module, state, output = evaluation
    state["on_request"] = lambda: state.update(tags=tags)
    assert_aborted(module, output)
    assert len(state["requests"]) == 1


@pytest.mark.parametrize("repair, unavailable", [(False, False), (True, False), (False, True)])
def test_stable_identity_checks_every_actual_request_and_preserves_failures(evaluation, repair, unavailable):
    module, state, output = evaluation
    state.update(repair=repair, unavailable=unavailable, digest="sha256:" + DIGEST)
    module.main()
    receipt = json.loads(output.read_text())
    assert receipt["artifact_digest"] == DIGEST
    assert receipt["fixture_fingerprint"] == module.fingerprint()
    verification = receipt["model_verification"]
    assert verification["request_attempts"] == len(state["requests"])
    assert verification["verified_request_boundaries"] == len(state["requests"])
    assert verification["tag_digest_checks"] == state["tag_reads"]
    assert "not immutable per-response attestation" in verification["limitation"]
    for index, event in enumerate(state["events"]):
        if event == "request":
            assert state["events"][index - 1] == state["events"][index + 1] == "tags"
    assert state["events"][-1] == "tags"
    if repair:
        assert state["answer_calls"] == 3
    if unavailable:
        assert all(row["source_decision"] == "needs_attention" for row in receipt["results"])
        assert all(row["failure_type"] == "GenerationUnavailable" for row in receipt["answers"])


def test_initial_wrong_digest_performs_no_inference(evaluation):
    module, state, output = evaluation
    state["digest"] = "b" * 64
    # argparse's existing preflight also rejects this boundary.
    with pytest.raises((RuntimeError, SystemExit)):
        module.main()
    assert not output.exists() and not state["requests"]


@pytest.mark.parametrize("identity_changed", [False, True])
def test_optional_repair_cannot_hide_identity_failure_by_returning_first_answer(
    evaluation, monkeypatch, identity_changed,
):
    module, state, _ = evaluation
    observed = "I saw the operator stop the exercise after comparing two readings."
    evidence = (generation.EvidenceItem(
        "S1", "Synthetic recollection.wav", "00:00–00:04", observed, "transcript",
    ),)
    calls = []

    def request(url, payload, **kwargs):
        assert url.endswith("/api/chat") and payload["model"] == MODEL
        calls.append(payload)
        if len(calls) == 1:
            return {"message": {"content": json.dumps({
                "answerable": True,
                "claims": [
                    {"text": "The machine transcript appears to say that " + observed,
                     "evidence_ids": ["S1"]},
                    {"text": "The machine transcript appears to say that a purchase order numbered PO-999 was approved.",
                     "evidence_ids": ["S1"]},
                ],
                "limitation": None,
                "missing_information": "",
            })}}
        assert len(calls) == 2
        assert "source-close grounding repair pass" in payload["messages"][0]["content"]
        if identity_changed:
            state["digest"] = "b" * 64
        raise generation.GenerationUnavailable("Synthetic unavailable optional repair.")

    monkeypatch.setattr(generation, "_bounded_json_request", request)
    client = module.DigestCheckedOllamaGenerator("http://127.0.0.1:11435", MODEL, DIGEST)
    service = generation.GroundedGenerationService(client)
    if identity_changed:
        with pytest.raises(module.EvaluationIdentityError, match="identity"):
            service.answer("What does the transcript say about the exercise?", evidence)
    else:
        answer = service.answer("What does the transcript say about the exercise?", evidence)
        assert answer.answerable and len(answer.claims) == 1
        assert observed in answer.claims[0].text
        assert answer.omitted_claims == 1
        assert client.verified_request_boundaries == 2
    assert len(calls) == 2


def test_corpus_manifest_contains_every_fingerprinted_control(evaluation, monkeypatch, tmp_path):
    module, state, _ = evaluation
    directory = tmp_path / "corpus"
    monkeypatch.setattr(sys, "argv", ["evaluate-workflow-quality.py", "--write-corpus", str(directory)])
    module.main()
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["questions"] == [{"id": "follow_up", "text": module.FOLLOW_UP},
        {"id": "unsupported_premise", "text": module.UNSUPPORTED_QUESTION}]
    assert manifest["usefulness_rubric"] == module.USEFULNESS_RUBRIC
    assert not state["requests"] and not state["tag_reads"]
