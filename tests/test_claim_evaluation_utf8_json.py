"""Synthetic UTF-8 CLI receipts and typed runtime identity, without network calls."""
import json
from pathlib import Path
import socket

import pytest

from case_intelligence import claim_evaluation as evaluation
from case_intelligence import generation
from tests.test_claim_evaluation import cli_module


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("CLI encoding regressions must never contact a model or network.")
    monkeypatch.setattr(generation.urllib.request, "urlopen", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


def non_utf8_default(monkeypatch, paths=None):
    """Read real bytes as Windows-1252 only when the caller omits encoding."""
    original = Path.read_text

    def read(path, encoding=None, errors=None):
        default = "cp1252" if paths is None or path in paths else "utf-8"
        return original(path, encoding=encoding or default, errors=errors)

    monkeypatch.setattr(Path, "read_text", read)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def cli_inputs(monkeypatch, tmp_path):
    cli = cli_module()
    raw = {"answerable": False, "claims": [], "limitation": None,
           "missing_information": "Synthetic café résumé."}
    pinned = evaluation.model_records("portable", generator_exercised=False)["components"][0]
    runtime = {"runtime_name": "Synthetic café", "runtime_version": "test-only",
        "accelerator": "none", "accelerator_memory_gib": 0, "driver": "Synthetic naïve",
        "model_artifact_sha256": "a" * 64, "offline_readiness": "not_exercised",
        "offline_evidence_sha256": None, "upstream_model_id": pinned["model_id"],
        "upstream_revision": pinned["revision"], "license": pinned["license"]}
    calls = []

    def response(*args, **kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": json.dumps(raw, ensure_ascii=False)}}]}

    monkeypatch.setattr(cli, "_bounded_json_get", lambda *args, **kwargs: {
        "data": [{"id": "synthetic-utf8"}]})
    monkeypatch.setattr(generation, "_bounded_json_request", response)
    profile = tmp_path / "runtime.json"
    evaluation.write_new(profile, runtime)
    capture_args = ["capture", "--backend", "openai", "--endpoint", "http://127.0.0.1:11435",
        "--model", "synthetic-utf8", "--profile", "portable", "--repetitions", "1",
        "--runtime-profile", str(profile)]
    return cli, profile, runtime, raw, calls, capture_args


def fill_grades(grades):
    grades["grader_id"] = "synthetic-grader"
    for sample in grades["samples"]:
        sample.update(answer_correct=False, rationale="Synthetic révision naïve.")
    return grades


def test_cli_utf8_capture_template_score_round_trip_under_non_utf8_default(
        monkeypatch, tmp_path, cli_inputs):
    cli, _, runtime, raw, calls, args = cli_inputs
    non_utf8_default(monkeypatch)
    capture_path, template_path, grades_path, score_path = (
        tmp_path / name for name in ("capture.json", "template.json", "grades.json", "score.json"))
    assert cli.main([*args, "--output", str(capture_path)]) == 0
    receipt = read_json(capture_path)
    assert receipt["runtime"] == {**runtime, "basis": "operator_declared_not_independently_verified"}
    assert len(calls) == len(receipt["results"]) == 11
    assert all(row["raw"] == raw for row in receipt["results"])
    evaluation.validate_receipt(receipt)
    assert cli.main(["grade-template", "--capture", str(capture_path),
                     "--output", str(template_path)]) == 0
    grades = fill_grades(read_json(template_path))
    evaluation.write_new(grades_path, grades)
    assert cli.main(["score", "--capture", str(capture_path), "--grades", str(grades_path),
                     "--output", str(score_path)]) == 0
    result = read_json(score_path)
    assert result["capture_sha256"] == receipt["receipt_sha256"]
    assert result["grades_sha256"] == evaluation.digest(grades)
    assert result["grades"] == grades
    assert result["receipt_sha256"] == evaluation.digest({
        key: value for key, value in result.items() if key != "receipt_sha256"})
    assert b"caf\xc3\xa9" in capture_path.read_bytes()
    assert b"r\xc3\xa9vision" in score_path.read_bytes()


@pytest.mark.parametrize("command,target", [
    ("grade-template", "capture"), ("score", "capture"), ("score", "grades"),
])
def test_each_cli_input_preserves_utf8_and_digest(monkeypatch, tmp_path, cli_inputs, command, target):
    cli, _, _, _, _, args = cli_inputs
    capture_path, grades_path, output = (
        tmp_path / name for name in ("capture.json", "grades.json", "output.json"))
    assert cli.main([*args, "--output", str(capture_path)]) == 0
    receipt = read_json(capture_path)
    grades = fill_grades(evaluation.grade_template(receipt))
    evaluation.write_new(grades_path, grades)
    non_utf8_default(monkeypatch, {capture_path if target == "capture" else grades_path})
    arguments = [command, "--capture", str(capture_path), "--output", str(output)]
    if command == "score":
        arguments += ["--grades", str(grades_path)]
    assert cli.main(arguments) == 0
    result = read_json(output)
    assert result["capture_sha256"] == receipt["receipt_sha256"]
    if command == "score":
        assert result["grades"] == grades
        assert result["grades_sha256"] == evaluation.digest(grades)


def test_model_catalog_preserves_utf8_manifest_metadata(monkeypatch, tmp_path):
    manifest = read_json(evaluation.ROOT / "config/models.json")
    manifest["models"][0]["synthetic_note"] = "Synthetic café résumé."
    (tmp_path / "config").mkdir()
    evaluation.write_new(tmp_path / "config/models.json", manifest)
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    non_utf8_default(monkeypatch)
    records = evaluation.model_records("portable", generator_exercised=False)
    assert records["components"][0]["synthetic_note"] == "Synthetic café résumé."
    assert records["manifest_sha256"] == evaluation.digest(manifest)


@pytest.mark.parametrize("reported", [int("1" * 64), None, ["1" * 64]])
def test_ollama_identity_rejects_nonstring_server_digest(monkeypatch, reported):
    cli = cli_module()
    monkeypatch.setattr(cli, "_bounded_json_get", lambda *args, **kwargs: {
        "models": [{"name": "synthetic", "digest": reported}]})
    _, check = cli.local_client("ollama", "http://127.0.0.1:11435", "synthetic", "1" * 64)
    with pytest.raises(cli.IdentityError):
        check()


@pytest.mark.parametrize("prefix", ["", "sha256:"])
def test_ollama_identity_preserves_plain_and_prefixed_digest_strings(monkeypatch, prefix):
    cli = cli_module()
    monkeypatch.setattr(cli, "_bounded_json_get", lambda *args, **kwargs: {
        "models": [{"name": "synthetic", "digest": prefix + "1" * 64}]})
    _, check = cli.local_client("ollama", "http://127.0.0.1:11435", "synthetic", "1" * 64)
    assert check() == {"method": "ollama_tag_digest_snapshots", "model": "synthetic",
                       "artifact_sha256": "1" * 64}
