"""Versioned, local-only model profiles for the transcription v2 pipeline.

This module deliberately imports only the Python standard library.  Importing it
must never initialize CUDA, contact a model hub, or require the optional ML
environment.  Runtime model imports live in :mod:`transcription_v2.pipeline` and
are performed only when a job is executed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Iterable


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """A model or runtime component whose license must appear in provenance."""

    name: str
    project_url: str
    license_name: str
    model_id: str | None = None
    gated: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "project_url": self.project_url,
            "license": self.license_name,
            "model_id": self.model_id,
            "gated": self.gated,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class TranscriptionProfile:
    """An immutable, user-facing quality profile.

    All profiles transcribe the source language first.  ``translation_model`` is
    kept separate so that a speed profile cannot accidentally ask Whisper Turbo
    to translate (Turbo is not trained for translation).
    """

    name: str
    display_name: str
    description: str
    asr_backend: str
    asr_model: str
    alignment_backend: str
    diarization_backend: str
    diarization_model: str
    translation_backend: str
    translation_model: str
    translation_targets: tuple[str, ...]
    compute_type: str
    batch_size: int
    beam_size: int
    best_of: int
    vad_method: str
    condition_on_previous_text: bool
    suppress_numerals: bool
    components: tuple[ComponentSpec, ...]
    notes: tuple[str, ...] = ()
    source_task: str = "transcribe"
    experimental: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.display_name:
            raise ValueError("profile name and display_name are required")
        if self.source_task != "transcribe":
            raise ValueError("profiles must always transcribe the source first")
        if self.batch_size < 1 or self.beam_size < 1 or self.best_of < 1:
            raise ValueError("batch_size, beam_size, and best_of must be positive")
        if not self.translation_targets:
            raise ValueError("at least one explicit translation target is required")
        if self.experimental:
            raise ValueError("experimental models may not be registered as user profiles")

    @property
    def asr_options(self) -> dict[str, Any]:
        """Return a fresh options mapping suitable for ``whisperx.load_model``."""

        return {
            "beam_size": self.beam_size,
            "best_of": self.best_of,
            "condition_on_previous_text": self.condition_on_previous_text,
            "suppress_numerals": self.suppress_numerals,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "source_task": self.source_task,
            "asr_backend": self.asr_backend,
            "asr_model": self.asr_model,
            "alignment_backend": self.alignment_backend,
            "diarization_backend": self.diarization_backend,
            "diarization_model": self.diarization_model,
            "translation_backend": self.translation_backend,
            "translation_model": self.translation_model,
            "translation_targets": list(self.translation_targets),
            "compute_type": self.compute_type,
            "batch_size": self.batch_size,
            "beam_size": self.beam_size,
            "best_of": self.best_of,
            "vad_method": self.vad_method,
            "condition_on_previous_text": self.condition_on_previous_text,
            "suppress_numerals": self.suppress_numerals,
            "components": [component.to_dict() for component in self.components],
            "notes": list(self.notes),
            "experimental": self.experimental,
        }


@dataclass(frozen=True, slots=True)
class ExperimentalCandidate:
    """A researched component that is intentionally unavailable in the UI."""

    name: str
    model_id: str
    project_url: str
    license_name: str
    purpose: str
    language_scope: str
    readiness: str
    blockers: tuple[str, ...]
    enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model_id": self.model_id,
            "project_url": self.project_url,
            "license": self.license_name,
            "purpose": self.purpose,
            "language_scope": self.language_scope,
            "readiness": self.readiness,
            "blockers": list(self.blockers),
            "enabled": self.enabled,
        }


_FASTER_WHISPER = ComponentSpec(
    name="faster-whisper",
    project_url="https://github.com/SYSTRAN/faster-whisper",
    license_name="MIT",
)
_WHISPER_WEIGHTS = ComponentSpec(
    name="OpenAI Whisper weights",
    project_url="https://github.com/openai/whisper",
    license_name="MIT",
)
_WHISPERX = ComponentSpec(
    name="WhisperX",
    project_url="https://github.com/m-bain/whisperX",
    license_name="BSD-2-Clause",
)
_WHISPERX_PACKAGED_VAD = ComponentSpec(
    name="WhisperX packaged pyannote VAD checkpoint",
    project_url="https://github.com/m-bain/whisperX",
    license_name="MODEL-SPECIFIC (ALLOWLIST REQUIRED)",
    notes=(
        "WhisperX 3.8.6 loads whisperx/assets/pytorch_model.bin locally. "
        "Record and approve the packaged checkpoint's hash and model license."
    ),
)
_COMMUNITY_1 = ComponentSpec(
    name="pyannote speaker-diarization-community-1",
    project_url="https://huggingface.co/pyannote/speaker-diarization-community-1",
    license_name="CC-BY-4.0",
    model_id="pyannote/speaker-diarization-community-1",
    gated=True,
    notes="Terms must be accepted once and attribution must be retained.",
)
_ALIGNMENT = ComponentSpec(
    name="WhisperX forced alignment",
    project_url="https://github.com/m-bain/whisperX",
    license_name="MODEL-SPECIFIC (ALLOWLIST REQUIRED)",
    notes=(
        "The selected language-specific wav2vec2/torchaudio checkpoint must pass "
        "the open-model license allowlist before deployment."
    ),
)

_COMMON_COMPONENTS: Final[tuple[ComponentSpec, ...]] = (
    _FASTER_WHISPER,
    _WHISPER_WEIGHTS,
    _WHISPERX,
    _WHISPERX_PACKAGED_VAD,
    _ALIGNMENT,
    _COMMUNITY_1,
)


BALANCED = TranscriptionProfile(
    name="balanced",
    display_name="Balanced",
    description="Recommended local profile for general recordings.",
    asr_backend="whisperx/faster-whisper",
    asr_model="large-v3",
    alignment_backend="whisperx-forced-alignment",
    diarization_backend="pyannote.audio",
    diarization_model="pyannote/speaker-diarization-community-1",
    translation_backend="whisperx/faster-whisper",
    translation_model="large-v3",
    translation_targets=("en",),
    compute_type="float16",
    batch_size=8,
    beam_size=5,
    best_of=5,
    # WhisperX 3.8.6 packages this pyannote VAD checkpoint in its wheel. Its
    # Silero adapter instead invokes torch.hub at runtime, which is unsuitable
    # for the offline confidential worker.
    vad_method="pyannote",
    condition_on_previous_text=False,
    suppress_numerals=False,
    components=_COMMON_COMPONENTS,
    notes=("Use as the initial reference configuration for reproducible evaluation.",),
)

HIGH_ACCURACY = TranscriptionProfile(
    name="high_accuracy",
    display_name="Highest accuracy",
    description="Lower-throughput local profile with a wider decoding search.",
    asr_backend="whisperx/faster-whisper",
    asr_model="large-v3",
    alignment_backend="whisperx-forced-alignment",
    diarization_backend="pyannote.audio",
    diarization_model="pyannote/speaker-diarization-community-1",
    translation_backend="whisperx/faster-whisper",
    translation_model="large-v3",
    translation_targets=("en",),
    compute_type="float16",
    batch_size=4,
    beam_size=8,
    best_of=8,
    vad_method="pyannote",
    condition_on_previous_text=False,
    suppress_numerals=False,
    components=_COMMON_COMPONENTS,
    notes=(
        "This profile is a hypothesis, not a quality guarantee; retain it only if "
        "the representative evaluation corpus shows a material gain.",
    ),
)

FAST = TranscriptionProfile(
    name="fast",
    display_name="Fast",
    description="Fast local draft profile; review is required for consequential use.",
    asr_backend="whisperx/faster-whisper",
    asr_model="turbo",
    alignment_backend="whisperx-forced-alignment",
    diarization_backend="pyannote.audio",
    diarization_model="pyannote/speaker-diarization-community-1",
    translation_backend="whisperx/faster-whisper",
    # Turbo is not trained for translation.  Translation therefore remains a
    # separate large-v3 pass even when source transcription uses Turbo.
    translation_model="large-v3",
    translation_targets=("en",),
    compute_type="float16",
    batch_size=16,
    beam_size=1,
    best_of=1,
    vad_method="pyannote",
    condition_on_previous_text=False,
    suppress_numerals=False,
    components=_COMMON_COMPONENTS,
    notes=(
        "Do not represent this profile as equivalent to the balanced profile.",
        "English translation, when requested, uses a separate large-v3 pass.",
    ),
)


DEFAULT_PROFILE_NAME: Final[str] = "high_accuracy"
_PROFILES: Final[dict[str, TranscriptionProfile]] = {
    profile.name: profile for profile in (BALANCED, HIGH_ACCURACY, FAST)
}


EXPERIMENTAL_CANDIDATES: Final[tuple[ExperimentalCandidate, ...]] = (
    ExperimentalCandidate(
        name="Parakeet-TDT 0.6B v3",
        model_id="nvidia/parakeet-tdt-0.6b-v3",
        project_url="https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3",
        license_name="CC-BY-4.0",
        purpose="High-throughput multilingual source transcription",
        language_scope="25 European languages",
        readiness="evaluation-only",
        blockers=(
            "Requires a NeMo/Transformers adapter and pinned container.",
            "Must beat large-v3 on the representative corpus and long-file tests.",
            "Does not replace diarization or speaker identification.",
        ),
    ),
    ExperimentalCandidate(
        name="Canary 1B v2",
        model_id="nvidia/canary-1b-v2",
        project_url="https://huggingface.co/nvidia/canary-1b-v2",
        license_name="CC-BY-4.0",
        purpose="Multilingual ASR and English-paired speech translation",
        language_scope="25 European languages; English paired translation",
        readiness="evaluation-only",
        blockers=(
            "Requires a NeMo adapter and translation artifact reconciliation.",
            "Language inventory must match actual users.",
            "Published benchmarks are not acceptance evidence for local audio.",
        ),
    ),
    ExperimentalCandidate(
        name="Canary-Qwen 2.5B",
        model_id="nvidia/canary-qwen-2.5b",
        project_url="https://huggingface.co/nvidia/canary-qwen-2.5b",
        license_name="CC-BY-4.0",
        purpose="English accuracy challenger",
        language_scope="English",
        readiness="evaluation-only",
        blockers=(
            "The model card limits trained input duration to 40 seconds.",
            "Requires validated chunk continuity and long-recording recovery.",
            "Requires a NeMo adapter and pinned container.",
        ),
    ),
)


def get_profile(name: str | None = None) -> TranscriptionProfile:
    """Return an immutable registered profile or raise a useful error."""

    normalized = (name or DEFAULT_PROFILE_NAME).strip().lower().replace("-", "_")
    try:
        return _PROFILES[normalized]
    except KeyError as exc:
        available = ", ".join(sorted(_PROFILES))
        raise KeyError(f"unknown transcription profile {name!r}; choose: {available}") from exc


def list_profiles() -> tuple[TranscriptionProfile, ...]:
    """Return profiles in stable UI order."""

    return (BALANCED, HIGH_ACCURACY, FAST)


def list_experimental_candidates() -> tuple[ExperimentalCandidate, ...]:
    return EXPERIMENTAL_CANDIDATES


def component_attributions(
    profiles: Iterable[TranscriptionProfile] | None = None,
) -> tuple[ComponentSpec, ...]:
    """Deduplicate component notices while retaining deterministic order."""

    selected = tuple(profiles) if profiles is not None else list_profiles()
    seen: set[tuple[str, str, str | None]] = set()
    result: list[ComponentSpec] = []
    for profile in selected:
        for component in profile.components:
            key = (component.name, component.license_name, component.model_id)
            if key not in seen:
                seen.add(key)
                result.append(component)
    return tuple(result)
