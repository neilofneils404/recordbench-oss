from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from transcription_v2.storage import (  # noqa: E402
    FileStorage,
    FileTooLargeError,
    InvalidStoragePathError,
    sanitize_filename,
    display_filename,
)


class TrackingStream:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.offset = 0
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        if size <= 0:
            raise AssertionError("ingest must request bounded positive chunks")
        self.read_sizes.append(size)
        result = self.payload[self.offset : self.offset + size]
        self.offset += len(result)
        return result


class FileStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "private-storage"
        self.storage = FileStorage(self.root, chunk_size=7)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_safe_filename_removes_both_path_styles_and_preserves_extension(self) -> None:
        self.assertEqual(sanitize_filename("../../folder/recording.wav"), "recording.wav")
        self.assertEqual(sanitize_filename(r"C:\evidence\call?.MP3"), "call_.MP3")
        self.assertEqual(sanitize_filename(".."), "upload.bin")
        self.assertEqual(sanitize_filename("\x00"), "upload.bin")
        long_name = "a" * 300 + ".wav"
        cleaned = sanitize_filename(long_name, max_length=80)
        self.assertEqual(len(cleaned), 80)
        self.assertTrue(cleaned.endswith(".wav"))
        self.assertNotIn("/", cleaned)
        self.assertNotIn("\\", cleaned)

    def test_display_filename_is_unicode_path_free_and_bounded(self) -> None:
        name = display_filename("../folder/Entrevista José\n.wav" + "x" * 400)
        self.assertTrue(name.startswith("Entrevista José_.wav"))
        self.assertNotIn("/", name)
        self.assertNotIn("\n", name)
        self.assertLessEqual(len(name), 255)

    def test_ingest_is_streamed_hashed_private_and_per_job(self) -> None:
        payload = b"0123456789" * 10
        stream = TrackingStream(payload)
        result = self.storage.ingest_stream(
            "job_01",
            stream,
            "../client call.wav",
            media_type="audio/wav",
            max_bytes=len(payload),
        )

        self.assertEqual(result.sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(result.size_bytes, len(payload))
        self.assertEqual(result.safe_name, "client_call.wav")
        self.assertEqual(result.absolute_path.read_bytes(), payload)
        self.assertTrue(all(size == 7 for size in stream.read_sizes))
        self.assertTrue(result.relative_path.startswith("jobs/job_01/input/"))
        self.assertEqual(result.absolute_path.stat().st_mode & 0o777, 0o400)
        paths = self.storage.job_paths("job_01")
        self.assertTrue(paths.input.is_dir())
        self.assertTrue(paths.work.is_dir())
        self.assertTrue(paths.output.is_dir())

    def test_same_content_and_name_reuses_content_address_without_partials(self) -> None:
        payload = b"same media bytes"
        first = self.storage.ingest_stream("job-a", io.BytesIO(payload), "call.wav")
        second = self.storage.ingest_stream("job-a", io.BytesIO(payload), "call.wav")
        self.assertEqual(first.absolute_path, second.absolute_path)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(list(first.absolute_path.parent.glob("*.part")), [])
        self.assertEqual(list(first.absolute_path.parent.glob(".upload-*")), [])

    def test_size_limit_removes_partial_upload(self) -> None:
        with self.assertRaises(FileTooLargeError):
            self.storage.ingest_stream(
                "limited-job", io.BytesIO(b"0123456789"), "large.wav", max_bytes=5
            )
        input_dir = self.storage.job_paths("limited-job").input
        self.assertEqual(list(input_dir.iterdir()), [])

    def test_relative_resolution_and_job_input_boundaries(self) -> None:
        result = self.storage.ingest_stream("job-one", io.BytesIO(b"x"), "x.wav")
        with self.storage.open_input("job-one", result.relative_path) as handle:
            self.assertEqual(handle.read(), b"x")
        with self.assertRaises(InvalidStoragePathError):
            self.storage.resolve_relative("../../etc/passwd")
        with self.assertRaises(InvalidStoragePathError):
            self.storage.resolve_relative("/etc/passwd")
        with self.assertRaises(InvalidStoragePathError):
            self.storage.open_input("job-two", result.relative_path)
        with self.assertRaises(InvalidStoragePathError):
            self.storage.job_paths("../escape")

    def test_delete_inputs_then_entire_job_tree(self) -> None:
        result = self.storage.ingest_stream("ephemeral", io.BytesIO(b"secret"), "call.wav")
        output = self.storage.output_path("ephemeral", "delivery.zip")
        output.write_bytes(b"delivery")
        job_root = self.storage.job_paths("ephemeral").root

        self.assertTrue(self.storage.delete_job_inputs("ephemeral"))
        self.assertFalse(result.absolute_path.exists())
        self.assertTrue(output.exists())
        self.assertFalse(self.storage.delete_job_inputs("ephemeral"))
        self.assertTrue(self.storage.delete_job_tree("ephemeral"))
        self.assertFalse(job_root.exists())
        self.assertFalse(self.storage.delete_job_tree("ephemeral"))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_delete_job_tree_refuses_symlink_boundary(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (outside / "must-remain").write_text("safe", encoding="utf-8")
        malicious = self.storage.jobs_root / "linked-job"
        malicious.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(InvalidStoragePathError):
            self.storage.delete_job_tree("linked-job")
        self.assertTrue((outside / "must-remain").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_ingest_refuses_symlinked_input_directory(self) -> None:
        paths = self.storage.job_paths("input-link")
        paths.input.rmdir()
        outside = Path(self.temporary.name) / "outside-input"
        outside.mkdir()
        paths.input.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(InvalidStoragePathError):
            self.storage.ingest_stream("input-link", io.BytesIO(b"secret"), "call.wav")
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
