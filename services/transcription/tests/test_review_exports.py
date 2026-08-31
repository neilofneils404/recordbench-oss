from __future__ import annotations

import io
import json
import tempfile
import unittest
import wave
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from transcription_v2.domain import IdentityMethod, IdentityStatus, TranscriptionOptions
from transcription_v2.review_exports import refresh_review_exports
from transcription_v2.runtime import build_runtime
from transcription_v2.settings import Settings
from transcription_v2.worker import JobWorker


def _wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16_000)
        recording.writeframes(b"\x00\x00" * 8_000)
    return output.getvalue()


class ReviewExportTests(unittest.TestCase):
    def test_source_stem_that_looks_like_legacy_translation_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = build_runtime(
                Settings(
                    data_root=root,
                    database_path=root / "jobs.sqlite3",
                    pipeline_backend="mock",
                )
            )
            job = runtime.store.create_job(
                owner_key="owner",
                options=TranscriptionOptions(),
                profile="balanced",
            )
            ingested = runtime.storage.ingest_stream(
                job.id,
                io.BytesIO(_wav_bytes()),
                "transcript.translation.en.wav",
                media_type="audio/wav",
            )
            runtime.store.register_file(
                job.id,
                owner_key="owner",
                original_name=ingested.original_name,
                safe_name=ingested.safe_name,
                relative_path=ingested.relative_path,
                media_type=ingested.media_type,
                size_bytes=ingested.size_bytes,
                sha256=ingested.sha256,
            )
            runtime.store.enqueue_job(job.id, "owner")
            self.assertTrue(JobWorker(runtime).run_once())

            refreshed = refresh_review_exports(runtime, job.id, "owner")
            output = runtime.storage.job_paths(job.id).output

            self.assertEqual(
                refreshed.zip_path,
                output / "transcript.translation.en.delivery.zip",
            )
            for suffix in ("docx", "txt", "srt", "manifest.json"):
                self.assertTrue((output / f"transcript.translation.en.{suffix}").is_file())

    def test_reviewed_text_and_confirmed_speaker_replace_delivery_not_machine_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = build_runtime(
                Settings(data_root=root, database_path=root / "jobs.sqlite3", pipeline_backend="mock")
            )
            job = runtime.store.create_job(
                owner_key="owner",
                options=TranscriptionOptions(),
                profile="balanced",
            )
            ingested = runtime.storage.ingest_stream(
                job.id,
                io.BytesIO(_wav_bytes()),
                "Review Session One.wav",
                media_type="audio/wav",
            )
            runtime.store.register_file(
                job.id,
                owner_key="owner",
                original_name=ingested.original_name,
                safe_name=ingested.safe_name,
                relative_path=ingested.relative_path,
                media_type=ingested.media_type,
                size_bytes=ingested.size_bytes,
                sha256=ingested.sha256,
            )
            runtime.store.enqueue_job(job.id, "owner")
            self.assertTrue(JobWorker(runtime).run_once())

            output = runtime.storage.job_paths(job.id).output
            legacy_names = {
                "transcript.docx",
                "transcript.json",
                "transcript.txt",
                "transcript.srt",
                "transcript.vtt",
                "transcript.csv",
                "transcript.manifest.json",
                "transcript.delivery.zip",
                "transcript.translation.en.docx",
                "transcript.translation.en.txt",
            }
            for legacy_name in legacy_names:
                (output / legacy_name).write_bytes(b"superseded legacy output")
            (output / "unrelated.keep").write_text("preserve", encoding="utf-8")

            segment = runtime.store.list_segments(job.id, "owner")[0]
            runtime.store.update_segment(
                segment.id,
                "owner",
                segment.revision,
                edited_text="Reviewed correction.",
            )
            mapping = runtime.store.list_speaker_mappings(job.id, "owner")[0]
            runtime.store.set_speaker_mapping(
                job.id,
                "owner",
                mapping.speaker_key,
                "Witness — confirmed by reviewer",
                identity_status=IdentityStatus.CONFIRMED,
                identity_method=IdentityMethod.MANUAL,
                expected_revision=mapping.revision,
            )
            refreshed = refresh_review_exports(runtime, job.id, "owner")

            self.assertEqual(
                refreshed.zip_path,
                output / "Review_Session_One.delivery.zip",
            )
            self.assertFalse(legacy_names & {path.name for path in output.iterdir()})
            self.assertEqual(
                (output / "unrelated.keep").read_text(encoding="utf-8"),
                "preserve",
            )
            text = (output / "Review_Session_One.txt").read_text(encoding="utf-8")
            self.assertIn("Reviewed correction.", text)
            self.assertIn("Witness — confirmed by reviewer", text)
            with zipfile.ZipFile(output / "Review_Session_One.docx") as word_document:
                word_text = " ".join(
                    ET.fromstring(
                        word_document.read("word/document.xml")
                    ).itertext()
                )
            self.assertIn("Reviewed correction.", word_text)
            self.assertIn("Witness — confirmed by reviewer", word_text)
            self.assertIn("with saved staff edits", word_text)
            reviewed = json.loads(
                (output / "Review_Session_One.json").read_text(encoding="utf-8")
            )
            self.assertEqual(reviewed["segments"][0]["text"], "Reviewed correction.")
            self.assertIn("Synthetic test transcript", reviewed["segments"][0]["model_text"])
            machine = json.loads(
                (runtime.storage.job_paths(job.id).work / "machine-result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("Synthetic test transcript", machine["segments"][0]["text"])
            self.assertNotEqual(machine["segments"][0]["text"], "Reviewed correction.")
            self.assertEqual(reviewed["translation"], machine["translation"])

            first_package = (output / "Review_Session_One.delivery.zip").read_bytes()
            first_reviewed_at = reviewed["provenance"]["review"]["reviewed_at"]
            with ThreadPoolExecutor(max_workers=2) as pool:
                bundles = list(
                    pool.map(
                        lambda _: refresh_review_exports(runtime, job.id, "owner"),
                        range(2),
                    )
                )
            self.assertTrue(all(bundle.zip_path is not None for bundle in bundles))
            self.assertEqual(
                first_package,
                (output / "Review_Session_One.delivery.zip").read_bytes(),
            )
            regenerated = json.loads(
                (output / "Review_Session_One.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                regenerated["provenance"]["review"]["reviewed_at"],
                first_reviewed_at,
            )


if __name__ == "__main__":
    unittest.main()
