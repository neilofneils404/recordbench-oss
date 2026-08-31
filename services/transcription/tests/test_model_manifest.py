from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from transcription_v2.cli import main
from transcription_v2.model_manifest import (
    MODEL_MANIFEST_SCHEMA,
    ModelManifestError,
    verify_model_manifest,
)


def _write_manifest(cache: Path, artifact: Path, *, sha256: str | None = None) -> Path:
    relative = artifact.relative_to(cache).as_posix()
    manifest = cache / "approved-model-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": MODEL_MANIFEST_SCHEMA,
                "artifacts": [
                    {
                        "role": "asr",
                        "model_id": "example/approved-model",
                        "revision": "0123456789abcdef",
                        "license": "MIT",
                        "files": [
                            {
                                "path": relative,
                                "size_bytes": artifact.stat().st_size,
                                "sha256": sha256
                                or hashlib.sha256(artifact.read_bytes()).hexdigest(),
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


class ModelManifestTests(unittest.TestCase):
    def test_valid_manifest_returns_path_free_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "models"
            artifact = cache / "snapshots" / "model.bin"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"approved fixture")
            manifest = _write_manifest(cache, artifact)

            public = verify_model_manifest(cache, manifest).public_dict()

            self.assertTrue(public["ready"])
            self.assertEqual(public["verified_file_count"], 1)
            serialized = json.dumps(public)
            self.assertNotIn(str(cache), serialized)
            self.assertNotIn("snapshots/model.bin", serialized)

    def test_verified_artifact_authorizes_snapshot_symlink_target_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "models"
            blob = cache / "models--pyannote--community-1" / "blobs" / "config"
            blob.parent.mkdir(parents=True)
            blob.write_text("pipeline: {}\n", encoding="utf-8")
            snapshot = (
                cache
                / "models--pyannote--community-1"
                / "snapshots"
                / "0123456789abcdef0123456789abcdef01234567"
            )
            snapshot.mkdir(parents=True)
            config = snapshot / "config.yaml"
            config.symlink_to("../../blobs/config")
            manifest = _write_manifest(cache, blob)
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["artifacts"][0].update(
                {
                    "role": "diarization",
                    "model_id": "pyannote/speaker-diarization-community-1",
                    "license": "CC-BY-4.0",
                }
            )
            manifest.write_text(json.dumps(document), encoding="utf-8")
            unlisted = cache / "unlisted.yaml"
            unlisted.write_text("pipeline: {}\n", encoding="utf-8")

            readiness = verify_model_manifest(cache, manifest)

            self.assertTrue(
                readiness.authorizes_file(
                    config,
                    role="diarization",
                    model_id="pyannote/speaker-diarization-community-1",
                )
            )
            self.assertFalse(
                readiness.authorizes_file(
                    unlisted,
                    role="diarization",
                    model_id="pyannote/speaker-diarization-community-1",
                )
            )
            self.assertFalse(
                readiness.authorizes_file(
                    config,
                    role="asr",
                    model_id="pyannote/speaker-diarization-community-1",
                )
            )
            serialized = json.dumps(readiness.public_dict())
            self.assertNotIn(str(cache), serialized)
            self.assertNotIn("config.yaml", serialized)

    def test_hash_mismatch_fails_with_stable_path_free_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "models"
            artifact = cache / "model.bin"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"changed")
            manifest = _write_manifest(cache, artifact, sha256="0" * 64)

            with self.assertRaises(ModelManifestError) as raised:
                verify_model_manifest(cache, manifest)

            self.assertEqual(raised.exception.code, "artifact_sha256_mismatch")
            self.assertNotIn(str(cache), str(raised.exception))

    def test_relative_escape_and_symlink_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "models"
            cache.mkdir()
            outside = root / "outside.bin"
            outside.write_bytes(b"outside")
            link = cache / "linked.bin"
            link.symlink_to(outside)
            manifest = _write_manifest(cache, link)

            with self.assertRaises(ModelManifestError) as raised:
                verify_model_manifest(cache, manifest)
            self.assertIn(raised.exception.code, {"artifact_symlink", "artifact_unreadable"})

            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["artifacts"][0]["files"][0]["path"] = "../outside.bin"
            manifest.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ModelManifestError) as raised:
                verify_model_manifest(cache, manifest)
            self.assertEqual(raised.exception.code, "manifest_invalid")

    def test_manifest_itself_must_stay_inside_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "models"
            cache.mkdir()
            outside_manifest = root / "manifest.json"
            outside_manifest.write_text("{}", encoding="utf-8")

            with self.assertRaises(ModelManifestError) as raised:
                verify_model_manifest(cache, outside_manifest)
            self.assertEqual(raised.exception.code, "manifest_outside_cache")

    def test_verify_models_cli_is_read_only_and_privacy_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "models"
            artifact = cache / "model.bin"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"approved fixture")
            manifest = _write_manifest(cache, artifact)
            output = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "TRANSCRIPTION_V2_DATA_ROOT": str(root / "data"),
                    "TRANSCRIPTION_V2_MODEL_CACHE": str(cache),
                    "TRANSCRIPTION_V2_MODEL_MANIFEST": str(manifest),
                },
                clear=True,
            ), redirect_stdout(output):
                exit_code = main(["verify-models"])

            self.assertEqual(exit_code, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["ready"])
            self.assertNotIn(str(root), output.getvalue())
            self.assertFalse((root / "data").exists())


if __name__ == "__main__":
    unittest.main()
