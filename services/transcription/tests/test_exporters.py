from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from transcription_v2.exporters import (  # noqa: E402
    build_manifest,
    format_srt_timestamp,
    format_vtt_timestamp,
    render_csv,
    render_docx,
    render_json,
    render_srt,
    render_translation_docx,
    render_translation_json,
    render_translation_txt,
    render_txt,
    render_vtt,
    source_export_base_name,
    write_export_bundle,
)


def sample_result() -> dict:
    source_text = "Hello, José. The amount is $12.50."
    return {
        "schema_version": "transcription-v2.1",
        "job_id": "tx-test-001",
        "status": "degraded",
        "source": {
            "file_name": "interview.wav",
            "sha256": "a" * 64,
            "bytes": 12345,
            "media_path_recorded": False,
        },
        "profile": {
            "name": "balanced",
            "asr_model": "large-v3",
            "diarization_model": "pyannote/speaker-diarization-community-1",
            "components": [
                {
                    "name": "faster-whisper",
                    "license": "MIT",
                    "project_url": "https://github.com/SYSTRAN/faster-whisper",
                }
            ],
        },
        "source_language": "es",
        "source_language_confidence": 0.92,
        "segments": [
            {
                "id": "seg_000001",
                "start": 0.0,
                "end": 2.3456,
                "text": source_text,
                "speaker": "SPEAKER_00",
                "confidence": 0.87654321,
                "overlap": False,
                "overlap_speakers": [],
                "words": [
                    {
                        "id": "word_00000001",
                        "text": "Hello",
                        "start": 0.0,
                        "end": 0.5,
                        "confidence": 0.9,
                        "speaker": "SPEAKER_00",
                        "overlap": False,
                    }
                ],
                "raw": {"text": source_text, "vendor_extension": "preserved"},
            },
            {
                "id": "seg_000002",
                "start": 2.3456,
                "end": 4.0,
                "text": "I agree.",
                "speaker": "SPEAKER_01",
                "confidence": None,
                "overlap": True,
                "overlap_speakers": ["SPEAKER_00", "SPEAKER_01"],
                "words": [],
                "raw": {"text": "I agree."},
            },
        ],
        "words": [],
        "diarization": {
            "requested": True,
            "status": "succeeded",
            "model": "pyannote/speaker-diarization-community-1",
            "speaker_count": 2,
            "speakers": ["SPEAKER_00", "SPEAKER_01"],
            "turns": [],
            "overlap_regions": [
                {
                    "id": "overlap_000001",
                    "start": 2.5,
                    "end": 3.0,
                    "speakers": ["SPEAKER_00", "SPEAKER_01"],
                }
            ],
        },
        "translation": {
            "status": "succeeded",
            "source_language": "es",
            "target_language": "en",
            "method": "separate-speech-translation-pass",
            "model": "large-v3",
            "text": "Hello, José. The amount is $12.50. I agree.",
            "segments": [
                {
                    "id": "seg_000001",
                    "start": 0.0,
                    "end": 4.0,
                    "text": "Hello, José. The amount is $12.50. I agree.",
                    "speaker": None,
                    "confidence": None,
                    "overlap": False,
                    "overlap_speakers": [],
                    "words": [],
                    "raw": {},
                }
            ],
            "raw": {"task": "translate"},
            "warnings": [
                {
                    "code": "translation_timestamps_not_forced_aligned",
                    "message": "Translation segment timing is approximate.",
                }
            ],
        },
        "raw": {"source_transcription": {"segments": [{"text": source_text}]}},
        "provenance": {
            "pipeline_version": "0.1.0",
            "completed_at": "2026-07-22T12:00:00.000Z",
            "source_preserved": True,
            "translation_is_separate_artifact": True,
            "delivery_only": True,
            "retention_managed_by_job_runner": True,
            "evidentiary_output_allowed": True,
            "engine": {"engine": "FixtureEngine", "mock": False},
        },
        "stages": [
            {
                "name": "source_transcription",
                "status": "succeeded",
                "duration_ms": 100,
                "warnings": [],
                "errors": [],
                "details": {},
            }
        ],
        "warnings": [
            {
                "stage": "diarization",
                "code": "review_overlap",
                "message": "Review the marked overlap.",
            }
        ],
        "errors": [],
    }


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = sample_result()

    def test_json_is_deterministic_and_preserves_raw_fields(self) -> None:
        first = render_json(self.result)
        second = render_json(self.result)
        self.assertEqual(first, second)
        payload = json.loads(first)
        self.assertEqual(
            payload["segments"][0]["raw"]["vendor_extension"], "preserved"
        )
        self.assertIn("José", first)
        without_raw = json.loads(render_json(self.result, include_raw=False))
        self.assertNotIn("raw", without_raw)
        self.assertNotIn("raw", without_raw["translation"])
        self.assertNotIn("raw", without_raw["segments"][0])
        self.assertNotIn("raw", without_raw["translation"]["segments"][0])

    def test_txt_keeps_source_and_translation_separate(self) -> None:
        text = render_txt(self.result)
        self.assertIn("SOURCE-LANGUAGE TRANSCRIPT", text)
        self.assertIn("TRANSLATION (EN)", text)
        self.assertIn("source transcript above is unchanged", text)
        self.assertLess(
            text.index("SOURCE-LANGUAGE TRANSCRIPT"), text.index("TRANSLATION (EN)")
        )

    def test_srt_and_vtt_emit_speaker_and_overlap_markers(self) -> None:
        srt = render_srt(self.result)
        vtt = render_vtt(self.result)
        self.assertIn("00:00:00,000 --> 00:00:02,346", srt)
        self.assertIn("SPEAKER_00: Hello", srt)
        self.assertIn("[OVERLAP: SPEAKER_00, SPEAKER_01]", srt)
        self.assertTrue(vtt.startswith("WEBVTT\n\n"))
        self.assertIn("00:00:02.346 --> 00:00:04.000", vtt)

    def test_translation_subtitles_do_not_copy_source_speaker_labels(self) -> None:
        translated = render_srt(self.result, translation=True)
        self.assertIn("Hello, José", translated)
        self.assertNotIn("SPEAKER_00", translated)
        translation_json = json.loads(render_translation_json(self.result))
        self.assertFalse(translation_json["source_transcript_mutated"])
        self.assertIn("Source transcript mutated: no", render_translation_txt(self.result))

    def test_csv_has_fixed_columns_and_unicode(self) -> None:
        content = render_csv(self.result)
        lines = content.splitlines()
        self.assertEqual(
            lines[0],
            "segment_id,start_seconds,end_seconds,speaker,confidence,overlap,overlap_speakers,word_count,text",
        )
        self.assertIn("José", content)
        self.assertIn("SPEAKER_00|SPEAKER_01", content)

    def test_csv_neutralizes_spreadsheet_formulas(self) -> None:
        self.result["segments"][0]["text"] = "=HYPERLINK(\"https://invalid\")"
        self.result["segments"][0]["speaker"] = " +SUM(1,1)"
        content = render_csv(self.result)
        self.assertIn("'=HYPERLINK", content)
        self.assertIn("' +SUM", content)

    def test_docx_is_deterministic_readable_ooxml_with_provenance_cues(self) -> None:
        first = render_docx(self.result)
        second = render_docx(self.result)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith(b"PK"))

        with zipfile.ZipFile(io.BytesIO(first)) as document:
            self.assertEqual(document.testzip(), None)
            self.assertIn("[Content_Types].xml", document.namelist())
            self.assertIn("word/document.xml", document.namelist())
            self.assertIn("word/styles.xml", document.namelist())
            xml = document.read("word/document.xml")
            text = " ".join(ET.fromstring(xml).itertext())

        self.assertIn("AI-generated transcript", text)
        self.assertIn("no human verification is recorded", text)
        self.assertIn("Source-Language Transcript", text)
        self.assertIn("Hello, José", text)
        self.assertIn("Translation (EN)", text)
        self.assertIn("source-language transcript above is unchanged", text)
        self.assertIn("Source SHA-256", text)
        self.assertIn("Review the marked overlap", text)
        self.assertLess(
            text.index("Source-Language Transcript"), text.index("Translation (EN)")
        )
        self.assertNotIn("vendor_extension", text)

    def test_translation_docx_is_separate_and_has_no_source_speaker_labels(self) -> None:
        content = render_translation_docx(self.result)
        with zipfile.ZipFile(io.BytesIO(content)) as document:
            xml = document.read("word/document.xml")
            text = " ".join(ET.fromstring(xml).itertext())
        self.assertIn("Machine-Generated Translation", text)
        self.assertIn("Source transcript changed:  No", text)
        self.assertIn("Hello, José", text)
        self.assertNotIn("SPEAKER_00", text)
        self.assertNotIn("Source-Language Transcript", text)

    def test_docx_replaces_xml_forbidden_control_characters(self) -> None:
        self.result["segments"][0]["text"] = "valid\u0000still valid"
        content = render_docx(self.result)
        with zipfile.ZipFile(io.BytesIO(content)) as document:
            xml = document.read("word/document.xml")
            text = "".join(ET.fromstring(xml).itertext())
        self.assertIn("valid\ufffdstill valid", text)

    def test_translation_docx_requires_translation(self) -> None:
        self.result.pop("translation")
        with self.assertRaises(ValueError):
            render_translation_docx(self.result)

    def test_timestamp_rounding_is_stable(self) -> None:
        self.assertEqual(format_srt_timestamp(1.9995), "00:00:02,000")
        self.assertEqual(format_vtt_timestamp(-1), "00:00:00.000")
        self.assertEqual(format_vtt_timestamp(3661.001), "01:01:01.001")


class ManifestTests(unittest.TestCase):
    def test_manifest_describes_ephemeral_delivery_not_storage(self) -> None:
        manifest = build_manifest(sample_result(), archive_name="case.delivery.zip")
        self.assertEqual(manifest["delivery"]["scope"], "transient-per-job-output")
        self.assertEqual(manifest["delivery"]["cleanup_owner"], "caller-job-runner")
        self.assertTrue(manifest["delivery"]["cleanup_required"])
        self.assertFalse(manifest["delivery"]["long_term_storage_implied"])
        self.assertFalse(manifest["source"]["media_included_in_delivery"])
        self.assertTrue(manifest["diarization"]["requested"])
        self.assertTrue(manifest["translation"]["separate_artifact"])

    def test_opted_out_diarization_is_not_exported_as_unavailable(self) -> None:
        result = sample_result()
        result["diarization"] = {
            "requested": False,
            "status": "skipped",
            "model": None,
            "speaker_count": 0,
            "speakers": [],
            "turns": [],
            "overlap_regions": [],
        }
        result["warnings"] = []
        for segment in result["segments"]:
            segment["speaker"] = None
            segment["overlap"] = False
            segment["overlap_speakers"] = []

        manifest = build_manifest(result)
        self.assertFalse(manifest["diarization"]["requested"])
        self.assertEqual(manifest["diarization"]["status"], "skipped")
        self.assertIsNone(manifest["diarization"]["model"])
        self.assertNotIn("SPEAKER_", render_srt(result))

        with zipfile.ZipFile(io.BytesIO(render_docx(result))) as document:
            text = " ".join(
                ET.fromstring(document.read("word/document.xml")).itertext()
            )
        self.assertIn("Speaker attribution:  not requested", text)
        self.assertNotIn("Speaker attribution was unavailable", text)
        self.assertNotIn("speaker labels", text)

    def test_legacy_result_without_requested_field_defaults_to_requested(self) -> None:
        result = sample_result()
        result["diarization"].pop("requested")
        self.assertTrue(build_manifest(result)["diarization"]["requested"])

    def test_manifest_fails_closed_without_evidentiary_provenance(self) -> None:
        result = sample_result()
        result["provenance"].pop("evidentiary_output_allowed")
        self.assertFalse(build_manifest(result)["evidentiary_output_allowed"])


class BundleTests(unittest.TestCase):
    def test_source_filename_becomes_safe_path_free_export_stem(self) -> None:
        self.assertEqual(source_export_base_name("Interview One.mp3"), "Interview_One")
        self.assertEqual(
            source_export_base_name(r"C:\\client\Matter 7\call?.WAV"),
            "call",
        )
        self.assertEqual(source_export_base_name("../../secret/hearing.m4a"), "hearing")
        self.assertEqual(source_export_base_name(".."), "transcript")
        self.assertEqual(source_export_base_name("CON.wav"), "_CON")

    def test_bundle_is_deterministic_and_contains_manifest(self) -> None:
        result = sample_result()
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = write_export_bundle(result, first_dir, base_name="case 123")
            second = write_export_bundle(result, second_dir, base_name="case 123")

            self.assertIsNotNone(first.zip_path)
            self.assertEqual(first.zip_sha256, second.zip_sha256)
            self.assertEqual(first.zip_path.read_bytes(), second.zip_path.read_bytes())
            self.assertEqual(first.manifest_path.name, "case_123.manifest.json")

            manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["delivery"]["archive_file"], "case_123.delivery.zip")
            self.assertNotIn("case_123.delivery.zip", manifest["artifacts"])
            self.assertIn("case_123.docx", manifest["artifacts"])
            self.assertIn("case_123.json", manifest["artifacts"])
            self.assertEqual(
                manifest["artifacts"]["case_123.docx"]["media_type"],
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            artifact = first.files["case_123.json"]
            delivered_json = json.loads(artifact.read_text(encoding="utf-8"))
            self.assertNotIn("raw", delivered_json)
            self.assertNotIn("raw", delivered_json["segments"][0])
            self.assertEqual(
                manifest["artifacts"]["case_123.json"]["sha256"],
                hashlib.sha256(artifact.read_bytes()).hexdigest(),
            )

            with zipfile.ZipFile(first.zip_path) as archive:
                names = archive.namelist()
                self.assertEqual(names, sorted(names))
                self.assertIn("case_123.docx", names)
                self.assertIn("case_123.txt", names)
                self.assertIn("case_123.srt", names)
                self.assertIn("case_123.manifest.json", names)
                self.assertIn("case_123.translation.en.docx", names)
                self.assertIn("case_123.translation.en.json", names)
                self.assertIn("case_123.translation.en.txt", names)
                self.assertNotIn("interview.wav", names)

    def test_output_directory_is_mandatory_and_root_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            write_export_bundle(sample_result(), None)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            write_export_bundle(sample_result(), Path("/"))


if __name__ == "__main__":
    unittest.main()
