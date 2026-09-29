from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import transcription_v2.resources as resources
from transcription_v2.resources import GpuState, readiness
from transcription_v2.settings import Settings


class _FakeDistribution:
    def __init__(self, root: Path, version: str = "3.8.6") -> None:
        self.root = root
        self.version = version

    def locate_file(self, relative: str) -> Path:
        return self.root / relative


class ReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.data = self.root / "data"
        self.cache = self.root / "models"
        self.diarization = self.cache / "approved" / "community-1"
        self.data.mkdir()
        self.cache.mkdir()
        self.diarization.mkdir(parents=True)
        (self.diarization / "config.yaml").write_text(
            "pipeline: {}\n", encoding="utf-8"
        )
        self.manifest = self.cache / "approved-model-manifest.json"
        self.manifest.write_text("{}", encoding="utf-8")
        self.settings = Settings(
            data_root=self.data,
            database_path=self.data / "jobs.sqlite3",
            pipeline_backend="whisperx",
            model_cache_dir=self.cache,
            model_manifest_path=self.manifest,
            minimum_free_disk_bytes=0,
            minimum_free_vram_mb=1,
        )
        self.environment = {
            "CUDA_VISIBLE_DEVICES": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TRANSCRIPTION_V2_DIARIZATION_MODEL_PATH": str(self.diarization),
        }

    def _report(self, distribution: _FakeDistribution) -> dict[str, object]:
        with mock.patch.dict(os.environ, self.environment, clear=True), mock.patch.object(
            resources.importlib.metadata,
            "distribution",
            return_value=distribution,
        ), mock.patch.object(
            resources,
            "gpu_states",
            return_value=[GpuState(1, "test-gpu", 48_000, 40_000, 0)],
        ), mock.patch.object(
            resources.shutil,
            "which",
            return_value="/usr/bin/tool",
        ):
            return readiness(self.settings)

    def test_real_backend_requires_pinned_package_and_packaged_vad(self) -> None:
        package_root = self.root / "site-packages"
        vad = package_root / "whisperx" / "assets" / "pytorch_model.bin"
        vad.parent.mkdir(parents=True)
        vad.write_bytes(b"fixture")

        report = self._report(_FakeDistribution(package_root))

        self.assertEqual(report["status"], "ready")
        checks = report["checks"]
        self.assertEqual(checks["whisperx_version"], "3.8.6")
        self.assertTrue(checks["whisperx_version_compatible"])
        self.assertTrue(checks["packaged_vad_present"])
        self.assertTrue(checks["model_manifest_required"])
        self.assertTrue(checks["model_manifest_present"])

    def test_missing_packaged_vad_fails_real_backend_readiness(self) -> None:
        report = self._report(_FakeDistribution(self.root / "empty-package"))

        self.assertEqual(report["status"], "not_ready")
        self.assertFalse(report["checks"]["packaged_vad_present"])

    def test_empty_diarization_directory_fails_readiness(self) -> None:
        package_root = self.root / "site-packages"
        vad = package_root / "whisperx" / "assets" / "pytorch_model.bin"
        vad.parent.mkdir(parents=True)
        vad.write_bytes(b"fixture")
        (self.diarization / "config.yaml").unlink()

        report = self._report(_FakeDistribution(package_root))

        self.assertEqual(report["status"], "not_ready")
        self.assertFalse(report["checks"]["diarization_model_present"])

    def test_explicit_degraded_mode_allows_asr_without_diarization(self) -> None:
        package_root = self.root / "site-packages"
        vad = package_root / "whisperx" / "assets" / "pytorch_model.bin"
        vad.parent.mkdir(parents=True)
        vad.write_bytes(b"fixture")
        (self.diarization / "config.yaml").unlink()
        self.settings = Settings(
            data_root=self.data,
            database_path=self.data / "jobs.sqlite3",
            pipeline_backend="whisperx",
            model_cache_dir=self.cache,
            model_manifest_path=self.manifest,
            minimum_free_disk_bytes=0,
            minimum_free_vram_mb=1,
            allow_degraded_diarization=True,
        )

        report = self._report(_FakeDistribution(package_root))

        self.assertEqual(report["status"], "degraded_ready")
        self.assertTrue(report["checks"]["degraded_diarization_allowed"])


if __name__ == "__main__":
    unittest.main()


class QueueReadinessTests(ReadinessTests):
    def _queue_report(self):
        with mock.patch.dict(os.environ, self.environment, clear=True), mock.patch.object(
            resources, "gpu_states", side_effect=AssertionError("API must not inspect GPUs")
        ), mock.patch.object(resources, "_whisperx_runtime_checks", side_effect=AssertionError("API must not inspect worker packages")), mock.patch.object(
            resources.shutil, "which", return_value="/usr/bin/tool"
        ):
            return resources.queue_readiness(self.settings)

    def test_api_can_admit_without_local_gpu_or_ml_packages(self):
        result = self._queue_report()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["scope"], "queue")
        self.assertNotIn("reserved_gpu_ready", result["checks"])
        self.assertEqual(result["worker_admission"], "artifact_verification_at_start_and_gpu_capacity_at_claim")

    def test_queue_still_requires_manifest_and_offline_configuration(self):
        self.manifest.unlink()
        self.assertEqual(self._queue_report()["status"], "not_ready")
        self.manifest.write_text("{}")
        self.environment["HF_HUB_OFFLINE"] = "0"
        self.assertEqual(self._queue_report()["status"], "not_ready")

    def test_queue_still_enforces_disk_reserve(self):
        from dataclasses import replace
        self.settings = replace(self.settings, minimum_free_disk_bytes=10**18)
        self.assertEqual(self._queue_report()["status"], "not_ready")

    def test_only_explicitly_qualified_whisperx_versions_are_accepted(self):
        package_root = self.root / "versions"
        vad = package_root / "whisperx/assets/pytorch_model.bin"
        vad.parent.mkdir(parents=True)
        vad.write_bytes(b"synthetic")
        for version, expected in [("3.8.6+recordbench.1", True), ("3.8.6+unknown.1", False), ("3.8.7", False)]:
            with self.subTest(version=version):
                result = self._report(_FakeDistribution(package_root, version))
                self.assertEqual(result["checks"]["whisperx_version_compatible"], expected)

    def test_worker_still_requires_executable_nemotron_interpreter(self):
        from transcription_v2.nemotron import MODEL_FILES
        model = self.cache / "nemotron"
        model.mkdir()
        for name in MODEL_FILES:
            (model / name).write_bytes(b"synthetic")
        interpreter = self.root / "worker-python"
        with mock.patch.dict(os.environ, {"TRANSCRIPTION_V2_NEMOTRON_PYTHON": str(interpreter)}):
            self.assertFalse(resources._diarization_config_present(model, "nemotron"))
            interpreter.write_text("#!/bin/sh\nexit 0\n")
            interpreter.chmod(0o600)
            self.assertFalse(resources._diarization_config_present(model, "nemotron"))
            interpreter.chmod(0o700)
            self.assertTrue(resources._diarization_config_present(model, "nemotron"))
