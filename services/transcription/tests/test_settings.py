from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from transcription_v2.settings import Settings


class SettingsTests(unittest.TestCase):
    def test_defaults_are_loopback_and_mock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"TRANSCRIPTION_V2_DATA_ROOT": tmp},
            clear=True,
        ):
            settings = Settings.from_env()
        self.assertEqual(settings.bind_host, "127.0.0.1")
        self.assertEqual(settings.pipeline_backend, "mock")
        self.assertEqual(settings.max_upload_bytes, 5 * 1024**3)
        self.assertEqual(settings.max_batch_upload_bytes, 5 * 1024**3)
        self.assertEqual(settings.max_files_per_request, 100)
        self.assertEqual(settings.max_retained_jobs_per_owner, 100)
        self.assertEqual(settings.max_retained_bytes_per_owner, 10 * 1024**3)
        self.assertEqual(settings.max_retained_jobs_global, 400)
        self.assertEqual(settings.max_media_duration_seconds, 12 * 60 * 60)
        self.assertEqual(settings.max_retained_bytes_global, 40 * 1024**3)
        self.assertEqual(settings.minimum_free_disk_bytes, 100 * 1024**3)
        self.assertNotIn("api_token", settings.public_dict())
        self.assertEqual(
            settings.public_dict()["max_batch_upload_bytes"],
            5 * 1024**3,
        )

    def test_legacy_quota_environment_derives_compatible_batch_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "TRANSCRIPTION_V2_DATA_ROOT": tmp,
                "TRANSCRIPTION_V2_MAX_UPLOAD_BYTES": str(2 * 1024**3),
                "TRANSCRIPTION_V2_MAX_RETAINED_BYTES_PER_OWNER": str(4 * 1024**3),
                "TRANSCRIPTION_V2_MAX_RETAINED_BYTES_GLOBAL": str(16 * 1024**3),
                "TRANSCRIPTION_V2_MIN_FREE_DISK_BYTES": str(20 * 1024**3),
            },
            clear=True,
        ):
            settings = Settings.from_env()

        self.assertEqual(settings.max_upload_bytes, 2 * 1024**3)
        self.assertEqual(settings.max_batch_upload_bytes, 4 * 1024**3)
        self.assertEqual(settings.max_retained_jobs_global, 400)
        self.assertEqual(settings.max_media_duration_seconds, 12 * 60 * 60)

    def test_non_loopback_requires_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "TRANSCRIPTION_V2_DATA_ROOT": tmp,
                "TRANSCRIPTION_V2_BIND_HOST": "0.0.0.0",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "API_TOKEN"):
                Settings.from_env()

    def test_owner_job_quota_must_hold_one_configured_upload_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                data_root=root,
                database_path=root / "jobs.sqlite3",
                max_files_per_request=3,
                max_retained_jobs_per_owner=2,
                max_retained_jobs_global=2,
            )

            with self.assertRaisesRegex(
                ValueError,
                "per-owner job quota cannot be smaller than one upload batch",
            ):
                settings.validate()

    def test_api_token_rejects_short_and_placeholder_values(self) -> None:
        for token in ("short", "replace-with-a-long-random-value"):
            with self.subTest(token=token), tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ,
                {
                    "TRANSCRIPTION_V2_DATA_ROOT": tmp,
                    "TRANSCRIPTION_V2_API_TOKEN": token,
                },
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "at least 32"):
                    Settings.from_env()

    def test_api_token_can_be_loaded_from_private_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "api-token"
            token_file.write_text("x" * 32 + "\n", encoding="utf-8")
            token_file.chmod(0o600)
            with patch.dict(
                os.environ,
                {
                    "TRANSCRIPTION_V2_DATA_ROOT": tmp,
                    "TRANSCRIPTION_V2_BIND_HOST": "0.0.0.0",
                    "TRANSCRIPTION_V2_API_TOKEN_FILE": str(token_file),
                },
                clear=True,
            ):
                settings = Settings.from_env()
            self.assertEqual(len(settings.api_token), 32)
            self.assertEqual(settings.api_token_file, token_file)
            self.assertNotIn("api_token", settings.public_dict())

    def test_api_token_sources_are_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "api-token"
            token_file.write_text("x" * 32, encoding="utf-8")
            token_file.chmod(0o600)
            with patch.dict(
                os.environ,
                {
                    "TRANSCRIPTION_V2_DATA_ROOT": tmp,
                    "TRANSCRIPTION_V2_API_TOKEN": "y" * 32,
                    "TRANSCRIPTION_V2_API_TOKEN_FILE": str(token_file),
                },
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "mutually exclusive"):
                    Settings.from_env()

    def test_api_token_file_rejects_unsafe_mode_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "api-token"
            token_file.write_text("x" * 32, encoding="utf-8")
            token_file.chmod(0o644)
            environment = {
                "TRANSCRIPTION_V2_DATA_ROOT": tmp,
                "TRANSCRIPTION_V2_API_TOKEN_FILE": str(token_file),
            }
            with patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesRegex(ValueError, "mode 0600"):
                    Settings.from_env()

            token_file.chmod(0o600)
            link = Path(tmp) / "linked-token"
            link.symlink_to(token_file)
            environment["TRANSCRIPTION_V2_API_TOKEN_FILE"] = str(link)
            with patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesRegex(ValueError, "non-symlink"):
                    Settings.from_env()

    def test_model_manifest_defaults_under_cache_and_cannot_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "models"
            with patch.dict(
                os.environ,
                {
                    "TRANSCRIPTION_V2_DATA_ROOT": tmp,
                    "TRANSCRIPTION_V2_MODEL_CACHE": str(cache),
                },
                clear=True,
            ):
                settings = Settings.from_env()
            self.assertEqual(
                settings.approved_model_manifest_path,
                cache / "approved-model-manifest.json",
            )

            with patch.dict(
                os.environ,
                {
                    "TRANSCRIPTION_V2_DATA_ROOT": tmp,
                    "TRANSCRIPTION_V2_MODEL_CACHE": str(cache),
                    "TRANSCRIPTION_V2_MODEL_MANIFEST": str(Path(tmp) / "outside.json"),
                },
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "must stay inside"):
                    Settings.from_env()

    def test_prepare_runtime_stays_under_configured_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pilot"
            settings = Settings(data_root=root, database_path=root / "jobs.sqlite3")
            settings.prepare_runtime()
            self.assertTrue((root / "jobs").is_dir())

            outside = Settings(
                data_root=root,
                database_path=Path(tmp) / "outside.sqlite3",
            )
            with self.assertRaisesRegex(ValueError, "must stay inside"):
                outside.prepare_runtime()

    def test_delivery_prefix_must_be_safe_and_relative_to_front_door(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "TRANSCRIPTION_V2_DATA_ROOT": tmp,
                "TRANSCRIPTION_V2_PUBLIC_DELIVERY_PREFIX": "//external.example/path",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "PUBLIC_DELIVERY_PREFIX"):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()
