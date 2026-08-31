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
