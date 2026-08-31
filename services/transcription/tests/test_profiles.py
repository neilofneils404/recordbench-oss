from __future__ import annotations

import os
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

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
from transcription_v2.profiles import (  # noqa: E402
    DEFAULT_PROFILE_NAME,
    component_attributions,
    get_profile,
    list_experimental_candidates,
    list_profiles,
)


class ProfileTests(unittest.TestCase):
    def test_registered_profiles_are_stable_and_non_experimental(self) -> None:
        profiles = list_profiles()
        self.assertEqual(
            [profile.name for profile in profiles],
            ["balanced", "high_accuracy", "fast"],
        )
        self.assertEqual(DEFAULT_PROFILE_NAME, "high_accuracy")
        self.assertTrue(all(not profile.experimental for profile in profiles))
        self.assertTrue(all(profile.source_task == "transcribe" for profile in profiles))

    def test_registered_profiles_use_packaged_offline_vad(self) -> None:
        for profile in list_profiles():
            with self.subTest(profile=profile.name):
                self.assertEqual(profile.vad_method, "pyannote")
                component_names = {item.name for item in profile.components}
                self.assertIn(
                    "WhisperX packaged pyannote VAD checkpoint",
                    component_names,
                )
                self.assertNotIn("Silero VAD", component_names)

    def test_fast_profile_never_uses_turbo_for_translation(self) -> None:
        profile = get_profile("fast")
        self.assertEqual(profile.asr_model, "turbo")
        self.assertEqual(profile.translation_model, "large-v3")
        self.assertEqual(profile.translation_targets, ("en",))

    def test_profile_is_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            get_profile("balanced").batch_size = 99  # type: ignore[misc]

    def test_profile_lookup_normalizes_hyphens(self) -> None:
        self.assertIs(get_profile("high-accuracy"), get_profile("high_accuracy"))
        with self.assertRaisesRegex(KeyError, "unknown transcription profile"):
            get_profile("hosted-premium")

    def test_component_attributions_include_gated_community_model(self) -> None:
        components = component_attributions()
        names = {component.name for component in components}
        self.assertIn("faster-whisper", names)
        community = next(
            component
            for component in components
            if component.model_id == "pyannote/speaker-diarization-community-1"
        )
        self.assertTrue(community.gated)
        self.assertEqual(community.license_name, "CC-BY-4.0")

    def test_experimental_nvidia_models_are_not_selectable_profiles(self) -> None:
        registered_names = {profile.name for profile in list_profiles()}
        candidates = list_experimental_candidates()
        self.assertGreaterEqual(len(candidates), 3)
        self.assertTrue(all(not candidate.enabled for candidate in candidates))
        self.assertTrue(all(candidate.name not in registered_names for candidate in candidates))
        self.assertTrue(any("Parakeet" in candidate.name for candidate in candidates))
        self.assertTrue(any("Canary" in candidate.name for candidate in candidates))


class RequestTests(unittest.TestCase):
    def test_request_exposes_speaker_bounds_and_deduplicated_hotwords(self) -> None:
        request = TranscriptionRequest(
            "audio.wav",
            profile="high-accuracy",
            min_speakers=2,
            max_speakers=4,
            hotwords=("Acme", "", "Acme", " Jane Doe "),
            translation_target="English",
        )
        self.assertEqual(request.profile, "high_accuracy")
        self.assertEqual(request.min_speakers, 2)
        self.assertEqual(request.max_speakers, 4)
        self.assertEqual(request.hotwords, ("Acme", "Jane Doe"))
        self.assertEqual(request.translation_target, "en")

    def test_request_rejects_inverted_speaker_bounds(self) -> None:
        with self.assertRaisesRegex(ValueError, "min_speakers"):
            TranscriptionRequest("audio.wav", min_speakers=4, max_speakers=2)


class MockPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.media_path = Path(self.temp_dir.name) / "synthetic-input.wav"
        self.media_path.write_bytes(b"not decoded by the mock engine")

    def test_engine_factory_defaults_to_mock_without_ml_imports(self) -> None:
        previous = os.environ.pop("TRANSCRIPTION_V2_PIPELINE", None)
        try:
            before = set(sys.modules)
            engine = create_pipeline_engine()
            after = set(sys.modules)
        finally:
            if previous is not None:
                os.environ["TRANSCRIPTION_V2_PIPELINE"] = previous
        self.assertIsInstance(engine, MockPipelineEngine)
        self.assertNotIn("whisperx", after - before)
        self.assertNotIn("torch", after - before)
        self.assertNotIn("pyannote.audio", after - before)

    def test_local_factory_is_also_lazy_and_uses_v2_cache_variable(self) -> None:
        cache_dir = str(Path(self.temp_dir.name) / "model-cache")
        previous = os.environ.get("TRANSCRIPTION_V2_MODEL_CACHE")
        os.environ["TRANSCRIPTION_V2_MODEL_CACHE"] = cache_dir
        try:
            before = set(sys.modules)
            engine = create_pipeline_engine("whisperx")
            after = set(sys.modules)
        finally:
            if previous is None:
                os.environ.pop("TRANSCRIPTION_V2_MODEL_CACHE", None)
            else:
                os.environ["TRANSCRIPTION_V2_MODEL_CACHE"] = previous
        self.assertIsInstance(engine, LocalWhisperXEngine)
        self.assertEqual(engine.model_cache_dir, cache_dir)
        self.assertNotIn("whisperx", after - before)
        self.assertNotIn("torch", after - before)

    def test_mock_pipeline_is_deterministic_and_non_evidentiary(self) -> None:
        events: list[tuple[str, str]] = []
        pipeline = TranscriptionPipeline(
            engine=MockPipelineEngine(),
            stage_callback=lambda stage, status: events.append((stage, status)),
        )
        result = pipeline.run(
            TranscriptionRequest(
                self.media_path,
                language="es",
                translation_target="en",
                min_speakers=1,
                max_speakers=2,
                hotwords=("Example Name",),
            )
        )
        payload = result.to_dict()

        self.assertEqual(result.status, PipelineStatus.DEGRADED)
        self.assertEqual(payload["source_language"], "es")
        self.assertIn("Synthetic test transcript", payload["segments"][0]["text"])
        self.assertEqual(payload["segments"][0]["speaker"], "SPEAKER_00")
        self.assertEqual(payload["translation"]["target_language"], "en")
        self.assertNotEqual(
            payload["translation"]["text"], payload["segments"][0]["text"]
        )
        self.assertFalse(payload["provenance"]["evidentiary_output_allowed"])
        self.assertTrue(payload["provenance"]["delivery_only"])
        self.assertTrue(
            any(
                warning["code"] == "mock_output_non_evidentiary"
                for warning in payload["warnings"]
            )
        )
        self.assertEqual(
            [stage["name"] for stage in payload["stages"]],
            list(TranscriptionPipeline.STAGE_NAMES),
        )
        self.assertIn(("source_transcription", "running"), events)
        self.assertIn(("source_transcription", "succeeded"), events)
        self.assertTrue(all(len(event) == 2 for event in events))


class AlignmentFailureEngine(MockPipelineEngine):
    def __init__(self) -> None:
        self.diarization_called = False

    def align_source(self, request, profile, source_result):  # type: ignore[no-untyped-def]
        raise RuntimeError("deliberate alignment failure")

    def diarize(self, request, profile):  # type: ignore[no-untyped-def]
        self.diarization_called = True
        return DiarizationOutput(turns=[], raw=[], native=[])


class DegradedStateTests(unittest.TestCase):
    def test_alignment_failure_is_visible_and_blocks_diarization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media_path = Path(directory) / "input.wav"
            media_path.write_bytes(b"test")
            engine = AlignmentFailureEngine()
            result = TranscriptionPipeline(engine=engine).run(
                TranscriptionRequest(media_path)
            )

        self.assertEqual(result.status, PipelineStatus.DEGRADED)
        self.assertEqual(result.stage("source_alignment").status, StageStatus.FAILED)
        self.assertEqual(result.stage("diarization").status, StageStatus.SKIPPED)
        self.assertFalse(engine.diarization_called)
        self.assertTrue(
            any(
                warning["code"] == "diarization_blocked_by_alignment"
                for warning in result.warnings
            )
        )
        self.assertTrue(result.segments, "raw source transcript must be retained")


if __name__ == "__main__":
    unittest.main()
