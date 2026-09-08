"""Synthetic artifact and native inference portability regressions."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import types

import pytest

from case_intelligence import generation, retrieval_worker

SPEC = importlib.util.spec_from_file_location("mac_models", Path(__file__).parents[1] / "scripts/mac-models.py")
assert SPEC is not None and SPEC.loader is not None
mac_models = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mac_models)


def test_ollama_direct_mode_applies_to_answers_and_source_reviews(monkeypatch):
    requests = []

    def request(url, payload, **kwargs):
        requests.append(payload)
        return {"message": {"content": "{}"}}

    monkeypatch.setattr(generation, "_bounded_json_request", request)
    monkeypatch.setenv("CASE_INTELLIGENCE_GENERATOR_BACKEND", "ollama")
    monkeypatch.setenv("CASE_INTELLIGENCE_GENERATOR_URL", "http://127.0.0.1:11435")
    monkeypatch.setenv("CASE_INTELLIGENCE_GENERATOR_MODEL", "synthetic-model")
    monkeypatch.setenv("CASE_INTELLIGENCE_GENERATOR_DISABLE_THINKING", "1")
    monkeypatch.setenv("CASE_INTELLIGENCE_GENERATOR_CONTEXT", "16384")
    monkeypatch.setenv("CASE_INTELLIGENCE_GENERATOR_MAX_OUTPUT_TOKENS", "1200")
    monkeypatch.setenv("CASE_INTELLIGENCE_GENERATOR_MAX_REVIEW_TOKENS", "400")
    client = generation.generator_from_environment()
    evidence = (generation.EvidenceItem("S1", "Synthetic note", "Page 1", "The synthetic crate is blue."),)
    client.generate(question="What color is the crate?", evidence=evidence)
    client.classify_source(criterion="Blue crates", include_guidance="", exclude_guidance="", evidence=evidence)
    assert client.disable_thinking is True
    assert [item["think"] for item in requests] == [False, False]
    assert [item["options"]["num_predict"] for item in requests] == [1200, 400]
    assert [item["options"]["num_ctx"] for item in requests] == [16384, 16384]
    assert requests[0]["format"] == generation.ANSWER_SCHEMA
    assert requests[1]["format"] == generation.REVIEW_SCHEMA


def test_ollama_defaults_preserve_existing_request_budget(monkeypatch):
    requests = []

    def request(url, payload, **kwargs):
        requests.append(payload)
        return {"message": {"content": "{}"}}

    monkeypatch.setattr(generation, "_bounded_json_request", request)
    client = generation.OllamaGenerator("http://127.0.0.1:11435", "synthetic-model")
    evidence = (generation.EvidenceItem("S1", "Synthetic note", "Page 1", "A synthetic crate."),)
    client.generate(question="What is recorded?", evidence=evidence)
    client.classify_source(criterion="Crates", include_guidance="", exclude_guidance="", evidence=evidence)
    assert all("think" not in item for item in requests)
    assert all("num_predict" not in item["options"] for item in requests)
    assert all(item["options"]["num_ctx"] == 8192 for item in requests)


@pytest.mark.parametrize("limit", [0, -1, 32769])
def test_ollama_explicit_output_limit_is_bounded(limit):
    with pytest.raises(ValueError, match="output limit"):
        generation.OllamaGenerator("http://127.0.0.1:11435", "synthetic", max_output_tokens=limit)


@pytest.mark.parametrize("context", [0, 2047, 131073])
def test_ollama_context_rejects_unbounded_or_unusable_budget(context):
    with pytest.raises(ValueError, match="generator context"):
        generation.OllamaGenerator("http://127.0.0.1:11435", "synthetic", context_tokens=context)


@pytest.mark.parametrize("device", ["cpu", "mps", "cuda"])
def test_retrieval_device_keeps_pins_and_offline_loading(monkeypatch, device):
    calls = []

    class Model:
        def __init__(self, model, **kwargs):
            calls.append((model, kwargs))

        def encode(self, texts, **kwargs):
            return [[1.0] + [0.0] * 767 for _ in texts]

        def predict(self, pairs):
            return [0.9, 0.1]

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=Model, CrossEncoder=Model))
    monkeypatch.setattr(retrieval_worker, "DEVICE", device)
    monkeypatch.setattr(retrieval_worker, "_embedding", None)
    monkeypatch.setattr(retrieval_worker, "_reranker", None)
    result = retrieval_worker.check_models()
    assert result["status"] == "ready"
    assert result["device"] == device
    assert [kwargs["revision"] for _, kwargs in calls] == [retrieval_worker.EMBEDDING_REVISION, retrieval_worker.RERANKER_REVISION]
    assert all(kwargs["device"] == device and kwargs["local_files_only"] is True and kwargs["trust_remote_code"] is False for _, kwargs in calls)


def test_retrieval_readiness_fails_closed_without_exposing_model_errors(monkeypatch):
    class Missing:
        def encode(self, *args, **kwargs):
            raise RuntimeError("synthetic sensitive runtime error")

        def predict(self, *args, **kwargs):
            return [float("nan"), 0.0]

    monkeypatch.setattr(retrieval_worker, "_embedding", Missing())
    monkeypatch.setattr(retrieval_worker, "_reranker", Missing())
    result = retrieval_worker.check_models()
    assert result["status"] == "not_ready"
    assert result["checks"] == {"embedding": "unavailable", "reranker": "invalid_output"}
    assert "sensitive" not in json.dumps(result)


@pytest.mark.parametrize("profile", ["4b", "9b"])
def test_pinned_mac_manifest_and_license_have_complete_digests(profile):
    value = mac_models.catalog(profile)
    assert value["model"] == f"qwen3.5:{profile}"
    assert value["license"] == "Apache-2.0"
    assert value["upstream_revision"] is None
    assert value["status"] == "evaluation-candidate"
    assert len(value["revision"]) == 71
    assert any(item["mediaType"].endswith(".license") for item in mac_models.artifacts(value))
    for item in mac_models.artifacts(value):
        assert len(item["digest"]) == 71 and item["size"] > 0


def test_model_verification_detects_tampered_blob(tmp_path):
    content = b"synthetic model blob"
    expected = "sha256:" + hashlib.sha256(content).hexdigest()
    manifest = b"synthetic pinned manifest"
    target = mac_models.manifest_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(manifest)
    blob = mac_models.blob_path(tmp_path, expected)
    blob.parent.mkdir()
    blob.write_bytes(content)
    value = {"revision": "sha256:" + hashlib.sha256(manifest).hexdigest(), "manifest": {"config": {"digest": expected, "size": len(content)}, "layers": []}}
    mac_models.verify(tmp_path, value)
    blob.write_bytes(b"tampered synthetic blob")
    with pytest.raises(RuntimeError, match="verification"):
        mac_models.verify(tmp_path, value)


def test_stage_refuses_mutable_tag_before_downloading_blobs(monkeypatch, tmp_path):
    monkeypatch.setattr(mac_models.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"changed tag"))
    monkeypatch.setattr(mac_models.shutil, "disk_usage", lambda path: types.SimpleNamespace(free=20 * 1024**3))
    with pytest.raises(RuntimeError, match="registry tag changed"):
        mac_models.stage(tmp_path, mac_models.catalog())
    assert not (tmp_path / "blobs").exists()


def test_download_size_cap_cleans_partial_file(monkeypatch, tmp_path):
    monkeypatch.setattr(mac_models.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"too much synthetic content"))
    target = tmp_path / "model"
    with pytest.raises(RuntimeError, match="exceeded pinned size"):
        mac_models.download("https://example.test/synthetic", target, "sha256:" + "0" * 64, 3)
    assert list(tmp_path.iterdir()) == []


def test_artifact_symlink_is_rejected(tmp_path):
    source = tmp_path / "synthetic-source"
    source.write_bytes(b"synthetic")
    linked = tmp_path / "linked"
    linked.symlink_to(source)
    with pytest.raises(RuntimeError, match="regular file"):
        mac_models.digest(linked)


@pytest.mark.parametrize("directory", ["blobs", "manifests"])
def test_model_vault_rejects_symlinked_parent_directory(tmp_path, directory):
    root = tmp_path / "vault"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / directory).symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlinks"):
        if directory == "blobs":
            mac_models.blob_path(root, "sha256:" + "0" * 64)
        else:
            mac_models.manifest_path(root)
    assert list(outside.iterdir()) == []


def test_cached_model_staging_does_not_reserve_duplicate_download_space(tmp_path, monkeypatch):
    content = b"synthetic weights\n" * 65536
    expected = "sha256:" + hashlib.sha256(content).hexdigest()
    manifest = {"config": {"digest": expected, "size": len(content), "mediaType": "synthetic"}, "layers": []}
    raw = json.dumps(manifest).encode()
    value = {"model": "qwen3.5:4b", "source": "https://example.test/synthetic", "revision": "sha256:" + hashlib.sha256(raw).hexdigest(), "manifest": manifest}
    blob = mac_models.blob_path(tmp_path, expected)
    blob.parent.mkdir()
    blob.write_bytes(content)
    monkeypatch.setattr(mac_models.shutil, "disk_usage", lambda root: types.SimpleNamespace(free=5 * 1024**3 + 4096))
    urls = []

    def fetch(url, **kwargs):
        urls.append(url)
        return io.BytesIO(raw)

    monkeypatch.setattr(mac_models.urllib.request, "urlopen", fetch)
    mac_models.stage(tmp_path, value)
    assert urls == [value["source"]]
    mac_models.verify(tmp_path, value)


def test_gold_limitation_requires_source_support_not_generic_omission_notice():
    from case_intelligence.model_portfolio_gold import model_portfolio_cases
    case = next(item for item in model_portfolio_cases() if item.case_id == "partially-readable-vehicle")
    answer = generation.VerifiedAnswer(
        answerable=True, introduction="", claims=(generation.VerifiedClaim("Falcon Ridge; license plate unreadable.", ("S1",)),),
        limitation=generation.VerifiedClaim("Some generated statements were omitted.", ()),
        missing_information="", used_evidence_ids=("S1",), model_called=True, elapsed_ms=1,
    )
    assert mac_models.case_failures(case, answer) == ["missing_limitation"]
