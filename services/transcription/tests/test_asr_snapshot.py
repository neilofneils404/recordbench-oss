"""Synthetic snapshots prove offline model identity without loading any weights."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from transcription_v2.asr_models import approved_asr_snapshot
from transcription_v2.model_manifest import verify_model_manifest, MODEL_MANIFEST_SCHEMA
from transcription_v2.pipeline import LocalWhisperXEngine, TranscriptionRequest, PipelineConfigurationError, create_pipeline_engine
from transcription_v2.profiles import get_profile


@pytest.fixture
def approved(tmp_path):
    root = tmp_path / "cache"
    revision = "a" * 40
    snapshot = root / "models--Systran--faster-whisper-large-v3/snapshots" / revision
    snapshot.mkdir(parents=True)
    files = []
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.json"):
        data = b"synthetic bytes for " + name.encode()
        path = snapshot / name
        path.write_bytes(data)
        files.append({"path": str(path.relative_to(root)), "size_bytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
    manifest = root / "approved-model-manifest.json"
    manifest.write_text(json.dumps({"schema_version": MODEL_MANIFEST_SCHEMA, "artifacts": [{
        "role": "asr", "model_id": "Systran/faster-whisper-large-v3", "revision": revision,
        "license": "MIT", "files": files}]}))
    return root, snapshot, verify_model_manifest(root, manifest)


@pytest.mark.parametrize("task", ["transcribe", "translate"])
def test_installed_adapter_loads_exact_snapshot_without_main_reference(approved, monkeypatch, task):
    root, snapshot, readiness = approved
    assert not (snapshot.parent.parent / "refs/main").exists()
    calls = []
    engine = create_pipeline_engine("whisperx", model_cache_dir=root, model_readiness=readiness)
    monkeypatch.setattr(engine, "_import_whisperx", lambda: SimpleNamespace(
        load_model=lambda *args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace()))
    request = TranscriptionRequest(audio_path=root / "synthetic-not-read.wav", device="cpu")
    engine._base_asr_pipeline(request, get_profile("balanced"), model_name="large-v3", task=task)
    assert calls[0][0][0] == str(snapshot)
    assert calls[0][1]["local_files_only"] is True
    reference = snapshot.parent.parent / "refs/main"
    reference.parent.mkdir()
    reference.write_text("b" * 40)
    assert approved_asr_snapshot(root, readiness, "large-v3") == snapshot


@pytest.mark.parametrize("change", ["missing", "modified", "extra", "outside-link", "directory-link"])
def test_invalid_snapshot_fails_before_importing_ml(approved, monkeypatch, tmp_path, change):
    root, snapshot, readiness = approved
    if change == "missing":
        (snapshot / "model.bin").unlink()
    elif change == "modified":
        (snapshot / "model.bin").write_bytes(b"changed synthetic weights")
    elif change == "extra":
        (snapshot / "unapproved.json").write_text("{}")
    elif change == "outside-link":
        outside = tmp_path / "outside"
        outside.write_bytes((snapshot / "model.bin").read_bytes())
        (snapshot / "model.bin").unlink()
        (snapshot / "model.bin").symlink_to(outside)
    else:
        (snapshot / "linked-directory").symlink_to(tmp_path, target_is_directory=True)
    engine = LocalWhisperXEngine(model_cache_dir=root, model_readiness=readiness)
    monkeypatch.setattr(engine, "_import_whisperx", lambda: pytest.fail("unapproved model reached ML loading"))
    request = TranscriptionRequest(audio_path=root / "synthetic-not-read.wav", device="cpu")
    with pytest.raises(PipelineConfigurationError) as caught:
        engine._base_asr_pipeline(request, get_profile("balanced"), model_name="large-v3", task="transcribe")
    assert str(root) not in str(caught.value)


def test_fast_profile_requires_separately_approved_artifact(approved):
    root, _, readiness = approved
    with pytest.raises(ValueError, match="not approved and staged"):
        approved_asr_snapshot(root, readiness, "turbo")


def test_snapshot_links_must_point_to_verified_blobs_inside_cache(approved):
    root, snapshot, _ = approved
    manifest = root / "approved-model-manifest.json"
    value = json.loads(manifest.read_text())
    blobs = snapshot.parent.parent / "blobs"
    blobs.mkdir()
    for row in value["artifacts"][0]["files"]:
        source = root / row["path"]
        blob = blobs / row["sha256"]
        source.rename(blob)
        source.symlink_to(blob)
        row["path"] = str(blob.relative_to(root))
    manifest.write_text(json.dumps(value))
    readiness = verify_model_manifest(root, manifest)
    assert approved_asr_snapshot(root, readiness, "large-v3") == snapshot


def test_hotword_wrapper_keeps_the_approved_snapshot(approved, monkeypatch):
    root, snapshot, readiness = approved
    calls = []
    base = SimpleNamespace(model=object(), vad_model=object())
    engine = LocalWhisperXEngine(model_cache_dir=root, model_readiness=readiness)
    monkeypatch.setattr(engine, "_import_whisperx", lambda: SimpleNamespace(
        load_model=lambda *args, **kwargs: calls.append((args, kwargs)) or base))
    request = TranscriptionRequest(audio_path=root / "synthetic-not-read.wav", device="cpu", hotwords=("synthetic",))
    engine._asr_pipeline(request, get_profile("balanced"), model_name="large-v3", task="transcribe")
    assert len(calls) == 2
    assert all(args[0] == str(snapshot) for args, _ in calls)
    assert calls[1][1]["model"] is base.model
