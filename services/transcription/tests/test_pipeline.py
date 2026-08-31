from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import transcription_v2.pipeline as pipeline_module  # noqa: E402
from transcription_v2.pipeline import (  # noqa: E402
    DiarizationOutput,
    LocalWhisperXEngine,
    MockPipelineEngine,
    PipelineStatus,
    StageStatus,
    TranscriptionPipeline,
    TranscriptionRequest,
    create_pipeline_engine,
)
from transcription_v2.profiles import get_profile  # noqa: E402


class OrderedMockEngine(MockPipelineEngine):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def transcribe_source(self, request, profile):  # type: ignore[no-untyped-def]
        self.calls.append("source_transcription")
        return super().transcribe_source(request, profile)

    def align_source(self, request, profile, source_result):  # type: ignore[no-untyped-def]
        self.calls.append("source_alignment")
        return super().align_source(request, profile, source_result)

    def diarize(self, request, profile):  # type: ignore[no-untyped-def]
        self.calls.append("diarization")
        return super().diarize(request, profile)

    def assign_speakers(  # type: ignore[no-untyped-def]
        self, request, profile, aligned_result, diarization
    ):
        self.calls.append("speaker_assignment")
        return super().assign_speakers(
            request, profile, aligned_result, diarization
        )

    def translate(self, request, profile):  # type: ignore[no-untyped-def]
        self.calls.append("translation")
        return super().translate(request, profile)


class TranslationFailureEngine(MockPipelineEngine):
    def translate(self, request, profile):  # type: ignore[no-untyped-def]
        raise RuntimeError("deliberate translation failure")


class AlignmentFailureEngine(MockPipelineEngine):
    def __init__(self) -> None:
        self.diarization_called = False

    def align_source(self, request, profile, source_result):  # type: ignore[no-untyped-def]
        raise RuntimeError("deliberate alignment failure")

    def diarize(self, request, profile):  # type: ignore[no-untyped-def]
        self.diarization_called = True
        return DiarizationOutput(turns=[], raw=[], native=[])


class EmptyAlignmentEngine(AlignmentFailureEngine):
    def align_source(self, request, profile, source_result):  # type: ignore[no-untyped-def]
        return {"segments": []}


class DiarizationTrackingEngine(MockPipelineEngine):
    def __init__(self) -> None:
        self.diarization_called = False
        self.speaker_assignment_called = False

    def diarize(self, request, profile):  # type: ignore[no-untyped-def]
        self.diarization_called = True
        return super().diarize(request, profile)

    def assign_speakers(  # type: ignore[no-untyped-def]
        self, request, profile, aligned_result, diarization
    ):
        self.speaker_assignment_called = True
        return super().assign_speakers(
            request, profile, aligned_result, diarization
        )

    def provenance(self):  # type: ignore[no-untyped-def]
        return {
            "engine": type(self).__name__,
            "mock": False,
            "media_inference_performed": True,
        }


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.media_path = Path(self.temp_dir.name) / "fixture.wav"
        self.media_path.write_bytes(b"opaque fixture bytes")

    def test_mock_full_run_is_ordered_callback_driven_and_non_evidentiary(self) -> None:
        engine = OrderedMockEngine()
        events: list[tuple[str, str]] = []
        result = TranscriptionPipeline(
            engine=engine,
            stage_callback=lambda stage, status: events.append((stage, status)),
        ).run(
            TranscriptionRequest(
                self.media_path,
                language="es",
                translation_target="en",
                min_speakers=1,
                max_speakers=3,
                hotwords=("Synthetic Name",),
            )
        )

        self.assertEqual(
            engine.calls,
            [
                "source_transcription",
                "source_alignment",
                "diarization",
                "speaker_assignment",
                "translation",
            ],
        )
        self.assertEqual(result.status, PipelineStatus.DEGRADED)
        self.assertFalse(result.provenance["evidentiary_output_allowed"])
        self.assertTrue(result.provenance["human_review_required"])
        self.assertTrue(result.provenance["engine"]["mock"])
        self.assertEqual(
            [stage.status for stage in result.stages],
            [
                StageStatus.SUCCEEDED,
                StageStatus.SUCCEEDED,
                StageStatus.SUCCEEDED,
                StageStatus.SUCCEEDED,
                StageStatus.SKIPPED,
                StageStatus.SUCCEEDED,
            ],
        )
        expected_event_pairs = {
            (stage, status)
            for stage in TranscriptionPipeline.STAGE_NAMES
            if stage != "speaker_identity"
            for status in ("running", "succeeded")
        }
        expected_event_pairs.add(("speaker_identity", "skipped"))
        self.assertTrue(expected_event_pairs.issubset(set(events)))
        self.assertTrue(all(len(event) == 2 for event in events))
        self.assertTrue(
            any(
                warning["code"] == "mock_output_non_evidentiary"
                for warning in result.warnings
            )
        )
        self.assertFalse(
            result.stage("speaker_identity").details["automatic_identity"]
        )
        self.assertTrue(
            result.stage("speaker_identity").details[
                "manual_confirmation_required"
            ]
        )
        self.assertTrue(result.diarization["requested"])
        self.assertEqual(
            result.diarization["model"],
            "pyannote/speaker-diarization-community-1",
        )
        self.assertTrue(result.provenance["request"]["diarize_speakers"])

    def test_three_speaker_overlap_is_disjoint_and_complete(self) -> None:
        regions = pipeline_module._overlap_regions(
            [
                {"start": 0.0, "end": 4.0, "speaker": "A"},
                {"start": 1.0, "end": 3.0, "speaker": "B"},
                {"start": 2.0, "end": 5.0, "speaker": "C"},
            ]
        )
        self.assertEqual(
            [
                (item["start"], item["end"], item["speakers"])
                for item in regions
            ],
            [
                (1.0, 2.0, ["A", "B"]),
                (2.0, 3.0, ["A", "B", "C"]),
                (3.0, 4.0, ["A", "C"]),
            ],
        )

    def test_source_is_preserved_when_separate_translation_fails(self) -> None:
        result = TranscriptionPipeline(engine=TranslationFailureEngine()).run(
            TranscriptionRequest(
                self.media_path,
                language="es",
                translation_target="en",
            )
        )

        self.assertEqual(result.status, PipelineStatus.DEGRADED)
        self.assertEqual(result.translation["status"], "failed")
        self.assertEqual(result.stage("translation").status, StageStatus.FAILED)
        self.assertIn("Synthetic test transcript", result.segments[0]["text"])
        self.assertIn("source_transcription", result.raw)
        self.assertTrue(result.provenance["source_preserved"])
        self.assertTrue(result.provenance["translation_is_separate_artifact"])
        self.assertTrue(
            any(
                warning["code"] == "source_transcript_preserved"
                for warning in result.warnings
            )
        )

    def test_alignment_failure_visibly_degrades_and_skips_diarization(self) -> None:
        engine = AlignmentFailureEngine()
        result = TranscriptionPipeline(engine=engine).run(
            TranscriptionRequest(self.media_path)
        )

        self.assertEqual(result.status, PipelineStatus.DEGRADED)
        self.assertEqual(result.stage("source_alignment").status, StageStatus.FAILED)
        self.assertEqual(result.stage("diarization").status, StageStatus.SKIPPED)
        self.assertEqual(result.diarization["status"], "skipped")
        self.assertFalse(engine.diarization_called)
        self.assertTrue(result.segments, "source ASR must remain available")
        self.assertTrue(
            any(
                warning["code"] == "diarization_blocked_by_alignment"
                for warning in result.warnings
            )
        )
        self.assertNotIn("deliberate alignment failure", str(result.to_dict()))

    def test_empty_alignment_cannot_erase_source_transcript(self) -> None:
        engine = EmptyAlignmentEngine()
        result = TranscriptionPipeline(engine=engine).run(
            TranscriptionRequest(self.media_path)
        )

        self.assertEqual(result.status, PipelineStatus.DEGRADED)
        self.assertEqual(result.stage("source_alignment").status, StageStatus.DEGRADED)
        self.assertEqual(result.stage("diarization").status, StageStatus.SKIPPED)
        self.assertFalse(engine.diarization_called)
        self.assertIn("Synthetic test transcript", result.segments[0]["text"])

    def test_unavailable_approved_diarization_model_is_deliberately_skipped(self) -> None:
        engine = DiarizationTrackingEngine()
        events: list[tuple[str, str]] = []
        result = TranscriptionPipeline(
            engine=engine,
            diarization_model_available=False,
            stage_callback=lambda stage, status: events.append((stage, status)),
        ).run(TranscriptionRequest(self.media_path))

        self.assertEqual(result.status, PipelineStatus.DEGRADED)
        self.assertEqual(result.stage("diarization").status, StageStatus.SKIPPED)
        self.assertEqual(result.diarization["status"], "skipped")
        self.assertTrue(result.diarization["requested"])
        self.assertIsNone(result.diarization["model"])
        self.assertEqual(result.diarization["speaker_count"], 0)
        self.assertFalse(engine.diarization_called)
        self.assertTrue(result.segments, "source transcript must remain deliverable")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.stage("diarization").errors, [])
        self.assertIn(("diarization", "skipped"), events)
        self.assertNotIn(("diarization", "running"), events)
        self.assertEqual(
            [
                warning["code"]
                for warning in result.warnings
                if warning["stage"] == "diarization"
            ],
            ["diarization_model_unavailable"],
        )

    def test_diarization_opt_out_is_intentional_and_not_degraded(self) -> None:
        engine = DiarizationTrackingEngine()
        events: list[tuple[str, str]] = []
        result = TranscriptionPipeline(
            engine=engine,
            # A deliberate opt-out must take precedence over model readiness.
            diarization_model_available=False,
            stage_callback=lambda stage, status: events.append((stage, status)),
        ).run(
            TranscriptionRequest(
                self.media_path,
                diarize_speakers=False,
                min_speakers=1,
                max_speakers=3,
            )
        )

        self.assertEqual(result.status, PipelineStatus.SUCCEEDED)
        self.assertEqual(result.stage("diarization").status, StageStatus.SKIPPED)
        self.assertEqual(result.diarization["status"], "skipped")
        self.assertFalse(result.diarization["requested"])
        self.assertIsNone(result.diarization["model"])
        self.assertIsNone(result.diarization["requested_model"])
        self.assertEqual(result.diarization["speaker_count"], 0)
        self.assertFalse(engine.diarization_called)
        self.assertFalse(engine.speaker_assignment_called)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])
        self.assertIsNone(result.segments[0].get("speaker"))
        self.assertFalse(
            result.stage("speaker_identity").details[
                "manual_confirmation_required"
            ]
        )
        self.assertFalse(result.provenance["request"]["diarize_speakers"])
        self.assertIn(("diarization", "skipped"), events)
        self.assertNotIn(("diarization", "running"), events)

    def test_alignment_failure_does_not_claim_opted_out_diarization_was_blocked(self) -> None:
        engine = AlignmentFailureEngine()
        result = TranscriptionPipeline(engine=engine).run(
            TranscriptionRequest(self.media_path, diarize_speakers=False)
        )

        self.assertEqual(result.status, PipelineStatus.DEGRADED)
        self.assertFalse(engine.diarization_called)
        self.assertFalse(result.diarization["requested"])
        diarization_warnings = [
            warning
            for warning in result.warnings
            if warning["stage"] == "diarization"
        ]
        self.assertEqual(diarization_warnings, [])
        alignment_warning = next(
            warning
            for warning in result.warnings
            if warning["code"] == "unaligned_source_retained"
        )
        self.assertNotIn("speaker", alignment_warning["message"].casefold())

    def test_diarization_request_flag_must_be_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "diarize_speakers"):
            TranscriptionRequest(
                self.media_path,
                diarize_speakers="false",  # type: ignore[arg-type]
            )

    def test_early_validation_failure_keeps_opt_out_metadata_terminal(self) -> None:
        result = TranscriptionPipeline(engine=DiarizationTrackingEngine()).run(
            TranscriptionRequest(
                self.media_path,
                translation_target="fr",
                diarize_speakers=False,
            )
        )

        self.assertEqual(result.status, PipelineStatus.FAILED)
        self.assertEqual(result.stage("diarization").status, StageStatus.SKIPPED)
        self.assertFalse(result.diarization["requested"])
        self.assertEqual(result.diarization["status"], "skipped")
        self.assertIsNone(result.diarization["model"])

    def test_mock_factory_and_run_never_import_ml_dependencies(self) -> None:
        with mock.patch.object(
            pipeline_module.importlib,
            "import_module",
            side_effect=AssertionError("mock mode attempted a lazy ML import"),
        ):
            engine = create_pipeline_engine("mock")
            result = TranscriptionPipeline(engine=engine).run(
                TranscriptionRequest(self.media_path)
            )
        self.assertIsInstance(engine, MockPipelineEngine)
        self.assertEqual(result.provenance["engine"]["media_inference_performed"], False)
        self.assertFalse(result.provenance["evidentiary_output_allowed"])

    def test_offline_alignment_probes_punkt_tab_directory(self) -> None:
        punkt_lookups: list[str] = []

        fake_nltk = SimpleNamespace(
            data=SimpleNamespace(find=lambda path: punkt_lookups.append(path))
        )
        fake_utils = SimpleNamespace(PUNKT_LANGUAGES={"en": "english"})
        fake_whisperx = SimpleNamespace(
            load_align_model=lambda **kwargs: (object(), {"language": "en"}),
            load_audio=lambda path: b"audio",
            align=lambda *args, **kwargs: {"segments": []},
        )

        def import_module(name):  # type: ignore[no-untyped-def]
            modules = {
                "whisperx": fake_whisperx,
                "whisperx.utils": fake_utils,
                "nltk": fake_nltk,
            }
            try:
                return modules[name]
            except KeyError as exc:
                raise AssertionError(f"unexpected module import: {name}") from exc

        request = TranscriptionRequest(self.media_path, language="en")
        engine = LocalWhisperXEngine(model_cache_dir="/staged/models")
        with mock.patch.object(pipeline_module.importlib, "import_module", import_module):
            result = engine.align_source(
                request,
                get_profile("balanced"),
                {"language": "en", "segments": []},
            )

        self.assertEqual(punkt_lookups, ["tokenizers/punkt_tab/english/"])
        self.assertEqual(result, {"segments": []})

    def test_local_asr_uses_pinned_whisperx_386_contract_and_offline_vad(self) -> None:
        load_calls: list[dict[str, object]] = []
        transcribe_calls: list[dict[str, object]] = []

        class FakeAsrPipeline:
            def transcribe(
                self,
                audio,
                *,
                batch_size,
                language,
                task,
            ):  # type: ignore[no-untyped-def]
                transcribe_calls.append(
                    {
                        "audio": audio,
                        "batch_size": batch_size,
                        "language": language,
                        "task": task,
                    }
                )
                return {"language": language, "segments": []}

        def load_model(
            whisper_arch,
            device,
            *,
            device_index,
            compute_type,
            asr_options,
            language,
            vad_method,
            task,
            download_root,
            local_files_only,
        ):  # type: ignore[no-untyped-def]
            load_calls.append(
                {
                    "whisper_arch": whisper_arch,
                    "device": device,
                    "device_index": device_index,
                    "compute_type": compute_type,
                    "asr_options": asr_options,
                    "language": language,
                    "vad_method": vad_method,
                    "task": task,
                    "download_root": download_root,
                    "local_files_only": local_files_only,
                }
            )
            return FakeAsrPipeline()

        fake_whisperx = SimpleNamespace(
            load_audio=lambda path: b"audio",
            load_model=load_model,
        )
        engine = LocalWhisperXEngine(model_cache_dir="/staged/models")
        request = TranscriptionRequest(
            self.media_path,
            language="en",
            device="cuda",
            device_index=2,
        )
        with mock.patch.object(
            pipeline_module.importlib,
            "import_module",
            return_value=fake_whisperx,
        ):
            result = engine.transcribe_source(request, get_profile("balanced"))

        self.assertEqual(result, {"language": "en", "segments": []})
        self.assertEqual(len(load_calls), 1)
        self.assertEqual(load_calls[0]["vad_method"], "pyannote")
        self.assertEqual(load_calls[0]["download_root"], "/staged/models")
        self.assertTrue(load_calls[0]["local_files_only"])
        self.assertEqual(
            transcribe_calls,
            [
                {
                    "audio": b"audio",
                    "batch_size": 8,
                    "language": "en",
                    "task": "transcribe",
                }
            ],
        )

    def test_local_diarization_uses_whisperx_submodule_contract(self) -> None:
        constructor_calls: list[dict[str, object]] = []
        inference_calls: list[tuple[str, int | None, int | None]] = []

        class NativeRows:
            def to_dict(self, *, orient):  # type: ignore[no-untyped-def]
                self.orient = orient
                return [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]

        class FakeDiarizationPipeline:
            def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
                constructor_calls.append(kwargs)

            def __call__(self, path, *, min_speakers, max_speakers):  # type: ignore[no-untyped-def]
                inference_calls.append((path, min_speakers, max_speakers))
                return NativeRows()

        fake_submodule = SimpleNamespace(DiarizationPipeline=FakeDiarizationPipeline)

        def import_module(name):  # type: ignore[no-untyped-def]
            if name == "whisperx.diarize":
                return fake_submodule
            raise AssertionError(f"unexpected module import: {name}")

        staged_model = Path(self.temp_dir.name) / "community-1"
        staged_model.mkdir()
        (staged_model / "config.yaml").write_text("pipeline: {}\n", encoding="utf-8")
        engine = LocalWhisperXEngine(diarization_model_path=staged_model)
        request = TranscriptionRequest(
            self.media_path,
            min_speakers=1,
            max_speakers=3,
            device="cuda",
            device_index=2,
        )
        with mock.patch.object(pipeline_module.importlib, "import_module", import_module):
            result = engine.diarize(request, get_profile("balanced"))

        self.assertEqual(
            constructor_calls,
            [
                {
                    "model_name": str(staged_model / "config.yaml"),
                    "token": None,
                    "device": "cuda:2",
                    "cache_dir": None,
                }
            ],
        )
        self.assertEqual(inference_calls, [(str(self.media_path), 1, 3)])
        self.assertEqual(len(result.turns), 1)
        self.assertEqual(result.turns[0]["start"], 0.0)
        self.assertEqual(result.turns[0]["end"], 1.0)
        self.assertEqual(result.turns[0]["speaker"], "SPEAKER_00")
        self.assertEqual(
            result.turns[0]["raw"],
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
        )

    def test_cached_diarization_snapshot_resolves_to_config_file(self) -> None:
        staged_model = Path(self.temp_dir.name) / "community-1-snapshot"
        staged_model.mkdir()
        config = staged_model / "config.yaml"
        config.write_text("pipeline: {}\n", encoding="utf-8")
        fake_hub = SimpleNamespace(
            snapshot_download=lambda **kwargs: str(staged_model)
        )
        engine = LocalWhisperXEngine(model_cache_dir="/staged/models")
        request = TranscriptionRequest(self.media_path, local_files_only=True)

        with mock.patch.object(
            pipeline_module.importlib,
            "import_module",
            return_value=fake_hub,
        ):
            resolved = engine._resolve_diarization_model(  # noqa: SLF001
                request, get_profile("balanced")
            )

        self.assertEqual(resolved, str(config))


if __name__ == "__main__":
    unittest.main()
