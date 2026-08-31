"""Auditable, local-only transcription pipeline orchestration.

The public data contracts in this module use only the Python standard library.
Optional ML dependencies are imported lazily by :class:`LocalWhisperXEngine` when
``run`` actually reaches an inference stage.  This keeps web workers, unit tests,
and export-only processes importable without CUDA, Torch, WhisperX, or pyannote.

The stage order is intentional and enforced:

``source transcription -> source alignment -> diarization -> translation``

Translation is a separate artifact.  It never replaces or mutates the aligned
source-language transcript.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import math
import os
import platform
import re
import threading
import time
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from .profiles import DEFAULT_PROFILE_NAME, TranscriptionProfile, get_profile


SCHEMA_VERSION = "transcription-v2.1"
PIPELINE_VERSION = "0.1.0"
_JOB_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class PipelineStatus(str, Enum):
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"
    FAILED = "failed"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineConfigurationError(ValueError):
    """A request or deployment setting is invalid before inference begins."""


class MissingRuntimeDependency(RuntimeError):
    """An optional ML dependency is unavailable in the inference worker."""


class UnsupportedTranslationError(RuntimeError):
    """The selected open model cannot produce the requested target language."""


class ModelApprovalError(PipelineConfigurationError):
    """A local model is absent, unapproved, or fails artifact verification."""


class PipelineCancellationRequested(RuntimeError):
    """The durable job was canceled at a safe boundary between model stages."""


_PUBLIC_STAGE_ERRORS: dict[str, str] = {
    "input_validation": "The uploaded media could not be validated.",
    "source_transcription": "Source transcription failed.",
    "source_alignment": "Word alignment failed.",
    "diarization": "Speaker separation failed.",
    "translation": "Translation failed.",
}


def _public_error_message(stage: str) -> str:
    """Return a stable delivery-safe error without dependency exception text."""

    return _PUBLIC_STAGE_ERRORS.get(stage, "This processing stage failed.")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True, slots=True)
class TranscriptionRequest:
    """Validated options for one local media file.

    ``hotwords`` and speaker bounds are per-job inputs and are recorded in the
    provenance manifest.  They are hints rather than assertions.
    """

    audio_path: str | Path
    profile: str = DEFAULT_PROFILE_NAME
    language: str | None = None
    translation_target: str | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None
    hotwords: tuple[str, ...] = ()
    alignment_model: str | None = None
    device: str = "cuda"
    device_index: int = 0
    local_files_only: bool = True
    job_id: str | None = None
    diarize_speakers: bool = True

    def __post_init__(self) -> None:
        path = Path(self.audio_path).expanduser()
        object.__setattr__(self, "audio_path", path)

        profile_name = self.profile.strip().lower().replace("-", "_")
        object.__setattr__(self, "profile", profile_name)

        if self.language is not None:
            language = self.language.strip().lower()
            object.__setattr__(self, "language", language or None)

        if self.translation_target is not None:
            target = self.translation_target.strip().lower()
            if target in {"english", "eng"}:
                target = "en"
            object.__setattr__(self, "translation_target", target or None)

        if not isinstance(self.diarize_speakers, bool):
            raise PipelineConfigurationError("diarize_speakers must be a boolean")

        if self.min_speakers is not None and self.min_speakers < 1:
            raise PipelineConfigurationError("min_speakers must be at least 1")
        if self.max_speakers is not None and self.max_speakers < 1:
            raise PipelineConfigurationError("max_speakers must be at least 1")
        if (
            self.min_speakers is not None
            and self.max_speakers is not None
            and self.min_speakers > self.max_speakers
        ):
            raise PipelineConfigurationError(
                "min_speakers cannot be greater than max_speakers"
            )
        if self.device_index < 0:
            raise PipelineConfigurationError("device_index cannot be negative")
        if not self.local_files_only:
            raise PipelineConfigurationError(
                "transcription v2 is offline-only; local_files_only cannot be disabled"
            )

        normalized_hotwords: list[str] = []
        seen: set[str] = set()
        for value in self.hotwords:
            word = str(value).strip()
            if word and word not in seen:
                seen.add(word)
                normalized_hotwords.append(word)
        object.__setattr__(self, "hotwords", tuple(normalized_hotwords))

        if self.job_id is not None:
            job_id = self.job_id.strip()
            if not _JOB_ID_RE.fullmatch(job_id):
                raise PipelineConfigurationError(
                    "job_id must be 1-128 ASCII letters, digits, '.', '_', or '-', "
                    "and must start with a letter or digit"
                )
            object.__setattr__(self, "job_id", job_id)


# Backwards-friendly name for API callers that prefer the more explicit noun.
PipelineRequest = TranscriptionRequest


@dataclass(slots=True)
class StageRecord:
    name: str
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    warnings: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    callback: Callable[[str, str], None] | None = field(
        default=None, repr=False, compare=False
    )

    def _notify(self) -> None:
        if self.callback is None:
            return
        try:
            # The progress contract is intentionally content-free.  Never pass
            # transcript text, paths, names, errors, or other recording data.
            self.callback(self.name, self.status.value)
        except Exception:
            # UI/progress transport failure must not change transcript results.
            pass

    def start(self, now: Callable[[], datetime], monotonic: Callable[[], float]) -> float:
        self.status = StageStatus.RUNNING
        self.started_at = now()
        self._notify()
        return monotonic()

    def finish(
        self,
        status: StageStatus,
        start_tick: float,
        now: Callable[[], datetime],
        monotonic: Callable[[], float],
    ) -> None:
        self.status = status
        self.finished_at = now()
        self.duration_ms = max(0, round((monotonic() - start_tick) * 1000))
        self._notify()

    def skip(self, reason: str, now: Callable[[], datetime]) -> None:
        timestamp = now()
        self.status = StageStatus.SKIPPED
        self.started_at = timestamp
        self.finished_at = timestamp
        self.duration_ms = 0
        self.details["reason"] = reason
        self._notify()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "duration_ms": self.duration_ms,
            "warnings": _plain_data(self.warnings),
            "errors": _plain_data(self.errors),
            "details": _plain_data(self.details),
        }


@dataclass(slots=True)
class DiarizationOutput:
    """Serializable diarization turns plus an engine-native assignment object."""

    turns: list[dict[str, Any]]
    raw: Any = None
    native: Any = field(default=None, repr=False)


@dataclass(slots=True)
class PipelineResult:
    job_id: str
    status: PipelineStatus
    source: dict[str, Any]
    profile: dict[str, Any]
    source_language: str | None = None
    source_language_confidence: float | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)
    diarization: dict[str, Any] = field(default_factory=dict)
    translation: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    stages: list[StageRecord] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def stage(self, name: str) -> StageRecord:
        for record in self.stages:
            if record.name == name:
                return record
        raise KeyError(name)

    def add_warning(self, stage: str, code: str, message: str) -> None:
        warning = {"stage": stage, "code": code, "message": message}
        self.warnings.append(warning)
        try:
            self.stage(stage).warnings.append(warning)
        except KeyError:
            pass

    def add_error(self, stage: str, exc: BaseException) -> None:
        del exc
        error = {
            "stage": stage,
            "code": f"{stage}_failed",
            # Exception text can contain absolute paths, tokens embedded by a
            # dependency, or audio-derived snippets.  Delivery artifacts expose
            # only a stable public code and message.
            "type": "ProcessingError",
            "message": _public_error_message(stage),
        }
        self.errors.append(error)
        try:
            self.stage(stage).errors.append(error)
        except KeyError:
            pass

    def degrade(self) -> None:
        if self.status is not PipelineStatus.FAILED:
            self.status = PipelineStatus.DEGRADED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "status": self.status.value,
            "source": _plain_data(self.source),
            "profile": _plain_data(self.profile),
            "source_language": self.source_language,
            "source_language_confidence": self.source_language_confidence,
            "segments": _plain_data(self.segments),
            "words": _plain_data(self.words),
            "diarization": _plain_data(self.diarization),
            "translation": _plain_data(self.translation),
            "raw": _plain_data(self.raw),
            "provenance": _plain_data(self.provenance),
            "stages": [stage.to_dict() for stage in self.stages],
            "warnings": _plain_data(self.warnings),
            "errors": _plain_data(self.errors),
        }


@runtime_checkable
class PipelineEngine(Protocol):
    """Dependency-injection boundary for local model implementations."""

    def transcribe_source(
        self, request: TranscriptionRequest, profile: TranscriptionProfile
    ) -> Mapping[str, Any]: ...

    def align_source(
        self,
        request: TranscriptionRequest,
        profile: TranscriptionProfile,
        source_result: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    def diarize(
        self, request: TranscriptionRequest, profile: TranscriptionProfile
    ) -> DiarizationOutput: ...

    def assign_speakers(
        self,
        request: TranscriptionRequest,
        profile: TranscriptionProfile,
        aligned_result: Mapping[str, Any],
        diarization: DiarizationOutput,
    ) -> Mapping[str, Any]: ...

    def translate(
        self, request: TranscriptionRequest, profile: TranscriptionProfile
    ) -> Mapping[str, Any]: ...

    def provenance(self) -> Mapping[str, Any]: ...


class MockPipelineEngine:
    """Deterministic, content-free engine for UI/worker/export integration tests.

    The engine never decodes or inspects media bytes.  The outer pipeline still
    validates the caller-provided file and computes its delivery checksum.  All
    mock results are visibly marked non-evidentiary and degraded at finalization.
    """

    _TEXT = "Synthetic test transcript. No media inference was performed."

    def transcribe_source(
        self, request: TranscriptionRequest, profile: TranscriptionProfile
    ) -> Mapping[str, Any]:
        del profile
        return {
            "language": request.language or "en",
            "language_confidence": None,
            "segments": [
                {
                    "start": 0.0,
                    "end": 3.0,
                    "text": self._TEXT,
                }
            ],
            "mock": True,
        }

    def align_source(
        self,
        request: TranscriptionRequest,
        profile: TranscriptionProfile,
        source_result: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del request, profile, source_result
        return {
            "segments": [
                {
                    "start": 0.0,
                    "end": 3.0,
                    "text": self._TEXT,
                    "words": [
                        {"word": "Synthetic", "start": 0.0, "end": 0.6, "score": 1.0},
                        {"word": " test", "start": 0.6, "end": 0.9, "score": 1.0},
                        {"word": " transcript.", "start": 0.9, "end": 1.5, "score": 1.0},
                        {"word": " No", "start": 1.5, "end": 1.8, "score": 1.0},
                        {"word": " media", "start": 1.8, "end": 2.1, "score": 1.0},
                        {"word": " inference", "start": 2.1, "end": 2.5, "score": 1.0},
                        {"word": " was", "start": 2.5, "end": 2.7, "score": 1.0},
                        {"word": " performed.", "start": 2.7, "end": 3.0, "score": 1.0},
                    ],
                }
            ],
            "mock": True,
        }

    def diarize(
        self, request: TranscriptionRequest, profile: TranscriptionProfile
    ) -> DiarizationOutput:
        del request, profile
        row = {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00", "mock": True}
        return DiarizationOutput(turns=[row], raw=[row], native=[row])

    def assign_speakers(
        self,
        request: TranscriptionRequest,
        profile: TranscriptionProfile,
        aligned_result: Mapping[str, Any],
        diarization: DiarizationOutput,
    ) -> Mapping[str, Any]:
        del request, profile, diarization
        assigned = _plain_data(aligned_result)
        for segment in assigned.get("segments", []):
            segment["speaker"] = "SPEAKER_00"
            for word in segment.get("words", []):
                word["speaker"] = "SPEAKER_00"
        assigned["mock"] = True
        return assigned

    def translate(
        self, request: TranscriptionRequest, profile: TranscriptionProfile
    ) -> Mapping[str, Any]:
        del profile
        if request.translation_target != "en":
            raise UnsupportedTranslationError("mock engine supports only the test target en")
        text = "Synthetic test translation. No media inference was performed."
        return {
            "source_language": request.language or "und",
            "target_language": "en",
            "segments": [{"start": 0.0, "end": 3.0, "text": text}],
            "mock": True,
        }

    def provenance(self) -> Mapping[str, Any]:
        return {
            "engine": type(self).__name__,
            "mock": True,
            "media_inference_performed": False,
            "evidentiary_use": False,
            "label": "SYNTHETIC TEST OUTPUT — DO NOT USE AS A TRANSCRIPT",
        }


class LocalWhisperXEngine:
    """Lazy local adapter for faster-whisper, WhisperX, and Community-1.

    Construction is side-effect free.  Model loading occurs only within an
    inference method.  The default ``local_files_only=True`` request setting is
    passed to faster-whisper and resolves Community-1 from the local Hugging Face
    cache, preventing an upload worker from silently downloading model weights.
    Alignment checkpoints must also be pre-staged and the worker should run with
    ``HF_HUB_OFFLINE=1`` as described in ``docs/OPEN_MODEL_POLICY.md``.
    """

    def __init__(
        self,
        *,
        model_cache_dir: str | Path | None = None,
        diarization_model_path: str | Path | None = None,
        auth_token_env: str = "HF_TOKEN",
    ) -> None:
        self.model_cache_dir = (
            str(Path(model_cache_dir).expanduser()) if model_cache_dir else None
        )
        self.diarization_model_path = (
            str(Path(diarization_model_path).expanduser())
            if diarization_model_path
            else None
        )
        self.auth_token_env = auth_token_env
        self._lock = threading.RLock()
        self._asr_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
        self._align_cache: OrderedDict[
            tuple[Any, ...], tuple[Any, Mapping[str, Any]]
        ] = OrderedDict()
        self._diarization_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()

    @staticmethod
    def _remember(
        cache: OrderedDict[tuple[Any, ...], Any],
        key: tuple[Any, ...],
        value: Any,
        *,
        maximum: int,
    ) -> Any:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > maximum:
            cache.popitem(last=False)
        return value

    @staticmethod
    def _import_whisperx() -> Any:
        try:
            return importlib.import_module("whisperx")
        except (ImportError, OSError) as exc:
            raise MissingRuntimeDependency(
                "WhisperX runtime is unavailable. Install the pinned v2 ML "
                "environment in the dedicated inference worker."
            ) from exc

    @staticmethod
    def _torch_device(request: TranscriptionRequest) -> str:
        if request.device == "cuda":
            return f"cuda:{request.device_index}"
        return request.device

    def _base_asr_pipeline(
        self,
        request: TranscriptionRequest,
        profile: TranscriptionProfile,
        *,
        model_name: str,
        task: str,
    ) -> Any:
        whisperx = self._import_whisperx()
        key = (
            model_name,
            task,
            request.language,
            request.device,
            request.device_index,
            profile.compute_type,
            profile.vad_method,
            tuple(sorted(profile.asr_options.items())),
        )
        with self._lock:
            cached = self._asr_cache.get(key)
            if cached is None:
                cached = whisperx.load_model(
                    model_name,
                    request.device,
                    device_index=request.device_index,
                    compute_type=profile.compute_type,
                    asr_options=profile.asr_options,
                    language=request.language,
                    vad_method=profile.vad_method,
                    task=task,
                    download_root=self.model_cache_dir,
                    local_files_only=request.local_files_only,
                )
                self._remember(self._asr_cache, key, cached, maximum=3)
            else:
                self._asr_cache.move_to_end(key)
            return cached

    def _asr_pipeline(
        self,
        request: TranscriptionRequest,
        profile: TranscriptionProfile,
        *,
        model_name: str,
        task: str,
    ) -> Any:
        base = self._base_asr_pipeline(
            request, profile, model_name=model_name, task=task
        )
        if not request.hotwords:
            return base

        # WhisperX stores decoding options on the pipeline.  Build a lightweight
        # wrapper around the already-loaded CTranslate2 model and VAD rather than
        # mutating shared options or loading another copy of the model weights.
        whisperx = self._import_whisperx()
        options = profile.asr_options
        options["hotwords"] = ", ".join(request.hotwords)
        return whisperx.load_model(
            model_name,
            request.device,
            device_index=request.device_index,
            compute_type=profile.compute_type,
            asr_options=options,
            language=request.language,
            vad_model=base.vad_model,
            model=base.model,
            task=task,
            download_root=self.model_cache_dir,
            local_files_only=request.local_files_only,
        )

    def transcribe_source(
        self, request: TranscriptionRequest, profile: TranscriptionProfile
    ) -> Mapping[str, Any]:
        whisperx = self._import_whisperx()
        audio = whisperx.load_audio(str(request.audio_path))
        # WhisperX pipelines carry mutable tokenizer/decoding state. Serialize
        # use of cached instances even if an embedding host calls concurrently.
        with self._lock:
            model = self._asr_pipeline(
                request, profile, model_name=profile.asr_model, task="transcribe"
            )
            return model.transcribe(
                audio,
                batch_size=profile.batch_size,
                language=request.language,
                task="transcribe",
            )

    def align_source(
        self,
        request: TranscriptionRequest,
        profile: TranscriptionProfile,
        source_result: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        whisperx = self._import_whisperx()
        language = str(source_result.get("language") or request.language or "").strip()
        if not language:
            raise RuntimeError("source language is unavailable; alignment cannot run")

        if request.local_files_only:
            # WhisperX 3.8.x otherwise calls nltk.download when Punkt is absent.
            # Fail visibly instead of permitting an inference job to attempt
            # network access.
            punkt_language = "english"
            try:
                nltk = importlib.import_module("nltk")
                whisperx_utils = importlib.import_module("whisperx.utils")
                punkt_languages = getattr(whisperx_utils, "PUNKT_LANGUAGES", {})
                punkt_language = punkt_languages.get(language, "english")
                # NLTK 3.9 stores ``punkt_tab`` as a language directory.  Its
                # compatibility loader accepts WhisperX's virtual ``.pickle``
                # resource name, but ``nltk.data.find`` does not.  Probe the
                # real on-disk directory so a correctly staged offline bundle
                # is not rejected before alignment starts.
                nltk.data.find(f"tokenizers/punkt_tab/{punkt_language}/")
            except (ImportError, LookupError) as exc:
                raise RuntimeError(
                    f"NLTK punkt_tab/{punkt_language} "
                    "is not pre-staged; offline alignment will not download it"
                ) from exc

        torch_device = self._torch_device(request)
        key = (language, request.alignment_model, torch_device, self.model_cache_dir)
        with self._lock:
            aligner = self._align_cache.get(key)
            if aligner is None:
                aligner = whisperx.load_align_model(
                    language_code=language,
                    device=torch_device,
                    model_name=request.alignment_model,
                    model_dir=self.model_cache_dir,
                    model_cache_only=request.local_files_only,
                )
                self._remember(self._align_cache, key, aligner, maximum=8)
            else:
                self._align_cache.move_to_end(key)
            align_model, metadata = aligner
            audio = whisperx.load_audio(str(request.audio_path))
            return whisperx.align(
                source_result.get("segments", []),
                align_model,
                metadata,
                audio,
                torch_device,
                return_char_alignments=False,
            )

    def _resolve_diarization_model(
        self, request: TranscriptionRequest, profile: TranscriptionProfile
    ) -> str:
        if self.diarization_model_path:
            return self._local_diarization_config(self.diarization_model_path)
        if not request.local_files_only:
            return profile.diarization_model

        try:
            hub = importlib.import_module("huggingface_hub")
        except ImportError as exc:
            raise MissingRuntimeDependency(
                "huggingface_hub is required to resolve the pre-staged "
                "Community-1 snapshot in offline mode"
            ) from exc
        token = os.environ.get(self.auth_token_env) or None
        try:
            snapshot = hub.snapshot_download(
                repo_id=profile.diarization_model,
                local_files_only=True,
                token=token,
                cache_dir=self.model_cache_dir,
            )
            return self._local_diarization_config(snapshot)
        except Exception as exc:
            raise RuntimeError(
                "Community-1 is not present in the local model cache. Pre-stage "
                "the approved revision; the inference worker will not download it."
            ) from exc

    @staticmethod
    def _local_diarization_config(model_path: str | Path) -> str:
        """Return the config file pyannote accepts for a local pipeline.

        Hugging Face snapshot resolution returns a directory, but
        ``pyannote.audio.Pipeline.from_pretrained`` distinguishes a local
        pipeline only when it receives the actual YAML file.
        """

        path = Path(model_path).expanduser()
        config = path if path.is_file() else path / "config.yaml"
        if not config.is_file():
            raise RuntimeError(
                "the staged Community-1 snapshot is missing config.yaml"
            )
        return str(config)

    def diarize(
        self, request: TranscriptionRequest, profile: TranscriptionProfile
    ) -> DiarizationOutput:
        try:
            # WhisperX 3.8.x does not re-export this class from its top-level
            # package.  Importing the submodule here keeps construction lazy
            # while matching the pinned runtime's public location.
            whisperx_diarize = importlib.import_module("whisperx.diarize")
        except (ImportError, OSError) as exc:
            raise MissingRuntimeDependency(
                "WhisperX diarization runtime is unavailable. Install the "
                "pinned v2 ML environment in the dedicated inference worker."
            ) from exc
        model_ref = self._resolve_diarization_model(request, profile)
        torch_device = self._torch_device(request)
        cache_key = (model_ref, torch_device)
        with self._lock:
            pipeline = self._diarization_cache.get(cache_key)
            if pipeline is None:
                pipeline = whisperx_diarize.DiarizationPipeline(
                    model_name=model_ref,
                    token=os.environ.get(self.auth_token_env) or None,
                    device=torch_device,
                    cache_dir=self.model_cache_dir,
                )
                self._remember(
                    self._diarization_cache, cache_key, pipeline, maximum=2
                )
            else:
                self._diarization_cache.move_to_end(cache_key)
            native = pipeline(
                str(request.audio_path),
                min_speakers=request.min_speakers,
                max_speakers=request.max_speakers,
            )
        try:
            rows = native.to_dict(orient="records")
        except (AttributeError, TypeError) as exc:
            raise RuntimeError("diarization returned an unsupported result shape") from exc
        turns = _normalize_turns(rows)
        return DiarizationOutput(turns=turns, raw=rows, native=native)

    def assign_speakers(
        self,
        request: TranscriptionRequest,
        profile: TranscriptionProfile,
        aligned_result: Mapping[str, Any],
        diarization: DiarizationOutput,
    ) -> Mapping[str, Any]:
        del request, profile
        whisperx = self._import_whisperx()
        if diarization.native is None:
            raise RuntimeError("native diarization output is unavailable for assignment")
        # fill_nearest=False avoids inventing a speaker where no turn overlaps.
        with self._lock:
            return whisperx.assign_word_speakers(
                diarization.native,
                dict(aligned_result),
                fill_nearest=False,
            )

    def translate(
        self, request: TranscriptionRequest, profile: TranscriptionProfile
    ) -> Mapping[str, Any]:
        target = request.translation_target
        if target != "en":
            raise UnsupportedTranslationError(
                "the approved Whisper translation adapter supports English output only"
            )
        whisperx = self._import_whisperx()
        audio = whisperx.load_audio(str(request.audio_path))
        with self._lock:
            # Recognition hotwords describe source-language audio. They are
            # deliberately not reused as translation prompts; the glossary is
            # retained for human review until a separately evaluated glossary
            # transformation exists.
            model = self._base_asr_pipeline(
                request,
                profile,
                model_name=profile.translation_model,
                task="translate",
            )
            translated = dict(
                model.transcribe(
                    audio,
                    batch_size=profile.batch_size,
                    language=request.language,
                    task="translate",
                )
            )
        # WhisperX reports the source language for the translate task.  Preserve
        # it explicitly while labeling output with the known target.
        translated["source_language"] = translated.get("language") or request.language
        translated["target_language"] = "en"
        return translated

    def provenance(self) -> Mapping[str, Any]:
        packages = (
            "whisperx",
            "faster-whisper",
            "ctranslate2",
            "torch",
            "pyannote.audio",
            "huggingface-hub",
        )
        versions: dict[str, str | None] = {}
        for package in packages:
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = None
        return {
            "engine": type(self).__name__,
            "packages": versions,
            "model_cache_dir_configured": bool(self.model_cache_dir),
            "diarization_model_path_configured": bool(self.diarization_model_path),
        }


def create_pipeline_engine(
    name: str | None = None,
    *,
    model_cache_dir: str | Path | None = None,
    diarization_model_path: str | Path | None = None,
) -> PipelineEngine:
    """Create an explicitly selected engine without importing ML packages.

    The safe default is ``mock``.  A deployment must opt into local inference by
    setting ``TRANSCRIPTION_V2_PIPELINE=local`` (or by injecting an engine).  No
    commercial or hosted provider is accepted by this factory.
    """

    selected = (name or os.environ.get("TRANSCRIPTION_V2_PIPELINE", "mock"))
    selected = selected.strip().lower().replace("-", "_")
    if selected in {"mock", "test", "synthetic"}:
        return MockPipelineEngine()
    if selected in {"local", "whisperx", "open_local"}:
        return LocalWhisperXEngine(
            model_cache_dir=(
                model_cache_dir
                or os.environ.get("TRANSCRIPTION_V2_MODEL_CACHE")
                or os.environ.get("TRANSCRIPTION_V2_MODEL_CACHE_DIR")
                or None
            ),
            diarization_model_path=(
                diarization_model_path
                or os.environ.get("TRANSCRIPTION_V2_DIARIZATION_MODEL_PATH")
                or None
            ),
        )
    raise PipelineConfigurationError(
        "TRANSCRIPTION_V2_PIPELINE must be 'mock' or 'local'; hosted/commercial "
        "engines are intentionally unsupported"
    )


class TranscriptionPipeline:
    """Run the ordered stages and return an explicit success/degraded/failure result."""

    STAGE_NAMES = (
        "input_validation",
        "source_transcription",
        "source_alignment",
        "diarization",
        "speaker_identity",
        "translation",
    )

    def __init__(
        self,
        engine: PipelineEngine | None = None,
        *,
        diarization_model_available: bool = True,
        now: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        stage_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        self.engine: PipelineEngine = engine or create_pipeline_engine()
        self._diarization_model_available = diarization_model_available
        self._now = now
        self._monotonic = monotonic
        self._stage_callback = stage_callback

    def run(
        self,
        request: TranscriptionRequest,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> PipelineResult:
        def check_cancellation() -> None:
            if cancel_requested is not None and cancel_requested():
                raise PipelineCancellationRequested(
                    "job cancellation requested at a pipeline stage boundary"
                )

        started_at = self._now()
        pipeline_tick = self._monotonic()
        check_cancellation()
        try:
            profile = get_profile(request.profile)
        except (KeyError, ValueError) as exc:
            profile = get_profile()
            return self._configuration_failure(request, profile, exc, started_at, pipeline_tick)

        placeholder_job_id = request.job_id or "pending-input-validation"
        result = PipelineResult(
            job_id=placeholder_job_id,
            status=PipelineStatus.SUCCEEDED,
            source={"file_name": Path(request.audio_path).name},
            profile=profile.to_dict(),
            stages=[
                StageRecord(name=name, callback=self._stage_callback)
                for name in self.STAGE_NAMES
            ],
            diarization={
                "requested": request.diarize_speakers,
                "status": "pending",
                "model": None,
                "requested_model": (
                    profile.diarization_model if request.diarize_speakers else None
                ),
                "turns": [],
                "speakers": [],
                "speaker_count": 0,
                "min_speakers_hint": request.min_speakers,
                "max_speakers_hint": request.max_speakers,
                "overlap_regions": [],
            },
            provenance={
                "pipeline_version": PIPELINE_VERSION,
                "created_at": _iso(started_at),
                "host": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                },
                "request": _request_provenance(request),
            },
        )

        if request.translation_target not in (None, *profile.translation_targets):
            exc = PipelineConfigurationError(
                f"profile {profile.name!r} supports translation targets "
                f"{profile.translation_targets}, not {request.translation_target!r}"
            )
            return self._fail_validation(result, exc, started_at, pipeline_tick)

        validation = result.stage("input_validation")
        validation_tick = validation.start(self._now, self._monotonic)
        try:
            path = Path(request.audio_path)
            if not path.exists():
                raise FileNotFoundError(f"input media does not exist: {path}")
            if not path.is_file():
                raise PipelineConfigurationError(f"input media is not a file: {path}")
            byte_size = path.stat().st_size
            if byte_size < 1:
                raise PipelineConfigurationError("input media is empty")
            digest = _sha256_file(path)
            result.job_id = request.job_id or f"tx-{digest[:16]}"
            result.source.update(
                {
                    "sha256": digest,
                    "bytes": byte_size,
                    "media_path_recorded": False,
                }
            )
            validation.details.update(
                {"sha256": digest, "bytes": byte_size, "local_file": True}
            )
            validation.finish(
                StageStatus.SUCCEEDED,
                validation_tick,
                self._now,
                self._monotonic,
            )
        except Exception as exc:
            validation.finish(
                StageStatus.FAILED,
                validation_tick,
                self._now,
                self._monotonic,
            )
            result.add_error("input_validation", exc)
            result.status = PipelineStatus.FAILED
            self._skip_after(result, "input_validation", "input validation failed")
            return self._finalize(result, started_at, pipeline_tick)

        check_cancellation()

        source = result.stage("source_transcription")
        source_tick = source.start(self._now, self._monotonic)
        try:
            raw_source = self.engine.transcribe_source(request, profile)
            if not isinstance(raw_source, Mapping):
                raise RuntimeError("source transcription returned a non-mapping result")
            source_language = str(
                raw_source.get("language") or request.language or ""
            ).strip()
            result.source_language = source_language or None
            result.source_language_confidence = _first_float(
                raw_source,
                ("language_confidence", "language_probability", "language_score"),
            )
            result.raw["source_transcription"] = _plain_data(raw_source)
            result.segments, result.words = _normalize_segments(
                raw_source.get("segments", [])
            )
            source.details.update(
                {
                    "model": profile.asr_model,
                    "task": "transcribe",
                    "language": result.source_language,
                    "segment_count": len(result.segments),
                    "word_count_before_alignment": len(result.words),
                    "hotword_count": len(request.hotwords),
                }
            )
            if not result.segments:
                result.add_warning(
                    "source_transcription",
                    "no_speech_segments",
                    "No speech segments were returned. Confirm that the file contains audible speech.",
                )
            source.finish(
                StageStatus.SUCCEEDED, source_tick, self._now, self._monotonic
            )
        except Exception as exc:
            source.finish(StageStatus.FAILED, source_tick, self._now, self._monotonic)
            result.add_error("source_transcription", exc)
            result.status = PipelineStatus.FAILED
            self._skip_after(result, "source_transcription", "source transcription failed")
            return self._finalize(result, started_at, pipeline_tick)

        check_cancellation()

        alignment_ok = False
        alignment = result.stage("source_alignment")
        if not result.segments:
            alignment.skip("no source speech segments", self._now)
            result.stage("diarization").skip(
                (
                    "no source speech segments"
                    if request.diarize_speakers
                    else "speaker separation was not requested"
                ),
                self._now,
            )
            result.diarization["status"] = "skipped"
        else:
            alignment_tick = alignment.start(self._now, self._monotonic)
            try:
                aligned = self.engine.align_source(request, profile, raw_source)
                if not isinstance(aligned, Mapping):
                    raise RuntimeError("alignment returned a non-mapping result")
                result.raw["source_alignment"] = _plain_data(aligned)
                aligned_segments, aligned_words = _normalize_segments(
                    aligned.get("segments", [])
                )
                alignment.details.update(
                    {
                        "backend": profile.alignment_backend,
                        "requested_model": request.alignment_model,
                        "segment_count": len(aligned_segments),
                        "word_count": len(aligned_words),
                    }
                )
                if not aligned_segments or not aligned_words:
                    alignment_message = (
                        "Alignment did not produce usable word timings. The raw "
                        "source transcript was retained and diarization was not "
                        "attempted."
                        if request.diarize_speakers
                        else "Alignment did not produce usable word timings. The "
                        "raw source transcript was retained."
                    )
                    result.add_warning(
                        "source_alignment",
                        "no_aligned_words",
                        alignment_message,
                    )
                    alignment.finish(
                        StageStatus.DEGRADED,
                        alignment_tick,
                        self._now,
                        self._monotonic,
                    )
                    result.degrade()
                else:
                    # Only replace the canonical source transcript after the
                    # aligned output has passed the minimum usability check.
                    # Empty or malformed alignment output must never erase a
                    # successful source-ASR result.
                    result.segments = aligned_segments
                    result.words = aligned_words
                    alignment_ok = True
                    alignment.finish(
                        StageStatus.SUCCEEDED,
                        alignment_tick,
                        self._now,
                        self._monotonic,
                    )
            except Exception as exc:
                alignment.finish(
                    StageStatus.FAILED,
                    alignment_tick,
                    self._now,
                    self._monotonic,
                )
                result.add_error("source_alignment", exc)
                alignment_message = (
                    "The raw source transcript was retained, but reliable word "
                    "timing and speaker assignment are unavailable."
                    if request.diarize_speakers
                    else "The raw source transcript was retained, but reliable "
                    "word timing is unavailable."
                )
                result.add_warning(
                    "source_alignment",
                    "unaligned_source_retained",
                    alignment_message,
                )
                result.degrade()

            if not alignment_ok:
                diarization_reason = (
                    "source alignment did not produce reliable word timings"
                    if request.diarize_speakers
                    else "speaker separation was not requested"
                )
                result.stage("diarization").skip(diarization_reason, self._now)
                result.diarization["status"] = "skipped"
                if request.diarize_speakers:
                    result.add_warning(
                        "diarization",
                        "diarization_blocked_by_alignment",
                        "Diarization was not silently applied to unaligned ASR segments.",
                    )

        check_cancellation()

        if alignment_ok and not request.diarize_speakers:
            diarization_stage = result.stage("diarization")
            diarization_stage.skip("speaker separation was not requested", self._now)
            diarization_stage.details.update(
                {
                    "requested": False,
                    "availability": "not_requested",
                }
            )
            result.diarization = {
                "requested": False,
                "status": "skipped",
                "model": None,
                "requested_model": None,
                "turns": [],
                "speakers": [],
                "speaker_count": 0,
                "min_speakers_hint": request.min_speakers,
                "max_speakers_hint": request.max_speakers,
                "overlap_regions": [],
            }
        elif alignment_ok and not self._diarization_model_available:
            diarization_stage = result.stage("diarization")
            diarization_stage.skip(
                "approved diarization model is unavailable", self._now
            )
            diarization_stage.details.update(
                {
                    "requested_model": profile.diarization_model,
                    "availability": "unavailable",
                }
            )
            result.diarization = {
                "requested": True,
                "status": "skipped",
                "model": None,
                "requested_model": profile.diarization_model,
                "turns": [],
                "speakers": [],
                "speaker_count": 0,
                "min_speakers_hint": request.min_speakers,
                "max_speakers_hint": request.max_speakers,
                "overlap_regions": [],
            }
            result.add_warning(
                "diarization",
                "diarization_model_unavailable",
                "Speaker separation is temporarily unavailable. The source transcript remains complete and downloadable without speaker labels.",
            )
            result.degrade()
        elif alignment_ok:
            diarization_stage = result.stage("diarization")
            diarization_tick = diarization_stage.start(self._now, self._monotonic)
            try:
                diarization_output = self.engine.diarize(request, profile)
                if not isinstance(diarization_output, DiarizationOutput):
                    raise RuntimeError("diarization returned an unsupported output object")
                assigned = self.engine.assign_speakers(
                    request, profile, aligned, diarization_output
                )
                if not isinstance(assigned, Mapping):
                    raise RuntimeError("speaker assignment returned a non-mapping result")
                turns = _normalize_turns(diarization_output.turns)
                overlap_regions = _overlap_regions(turns)
                result.raw["diarization"] = _plain_data(diarization_output.raw)
                result.raw["speaker_assignment"] = _plain_data(assigned)
                result.segments, result.words = _normalize_segments(
                    assigned.get("segments", []), turns=turns
                )
                speakers = sorted(
                    {
                        str(turn["speaker"])
                        for turn in turns
                        if turn.get("speaker") not in (None, "")
                    }
                )
                result.diarization = {
                    "requested": True,
                    "status": "succeeded" if turns else "degraded",
                    "model": profile.diarization_model,
                    "requested_model": profile.diarization_model,
                    "turns": turns,
                    "speakers": speakers,
                    "speaker_count": len(speakers),
                    "min_speakers_hint": request.min_speakers,
                    "max_speakers_hint": request.max_speakers,
                    "overlap_regions": overlap_regions,
                }
                diarization_stage.details.update(
                    {
                        "model": profile.diarization_model,
                        "turn_count": len(turns),
                        "speaker_count": len(speakers),
                        "overlap_region_count": len(overlap_regions),
                    }
                )
                if turns:
                    diarization_stage.finish(
                        StageStatus.SUCCEEDED,
                        diarization_tick,
                        self._now,
                        self._monotonic,
                    )
                else:
                    result.add_warning(
                        "diarization",
                        "no_speaker_turns",
                        "Diarization returned no speaker turns; source transcript remains usable but unattributed.",
                    )
                    result.degrade()
                    diarization_stage.finish(
                        StageStatus.DEGRADED,
                        diarization_tick,
                        self._now,
                        self._monotonic,
                    )
            except Exception as exc:
                diarization_stage.finish(
                    StageStatus.FAILED,
                    diarization_tick,
                    self._now,
                    self._monotonic,
                )
                result.add_error("diarization", exc)
                result.add_warning(
                    "diarization",
                    "speaker_attribution_unavailable",
                    "Source transcription and alignment succeeded, but speaker attribution failed and is visibly marked unavailable.",
                )
                result.diarization["status"] = "failed"
                result.degrade()

        check_cancellation()

        identity_stage = result.stage("speaker_identity")
        if result.diarization.get("status") == "succeeded":
            identity_stage.skip(
                "automatic real-world identity is disabled; staff confirmation is required",
                self._now,
            )
            identity_stage.details.update(
                {
                    "automatic_identity": False,
                    "manual_confirmation_required": True,
                }
            )
        elif not request.diarize_speakers:
            identity_stage.skip(
                "speaker separation was not requested",
                self._now,
            )
            identity_stage.details.update(
                {
                    "automatic_identity": False,
                    "manual_confirmation_required": False,
                }
            )
        else:
            identity_stage.skip(
                "speaker identity is unavailable without reliable voice clusters",
                self._now,
            )

        translation_stage = result.stage("translation")
        if request.translation_target is None:
            translation_stage.skip("translation was not requested", self._now)
        elif not result.segments:
            translation_stage.skip("no source speech segments", self._now)
            result.translation = {
                "status": "skipped",
                "source_language": result.source_language,
                "target_language": request.translation_target,
                "method": "separate-speech-translation-pass",
                "model": profile.translation_model,
                "text": "",
                "segments": [],
                "raw": None,
                "warnings": [],
            }
        elif (
            result.source_language
            and request.translation_target == result.source_language.lower()
        ):
            tick = translation_stage.start(self._now, self._monotonic)
            result.translation = {
                "status": "succeeded",
                "source_language": result.source_language,
                "target_language": request.translation_target,
                "method": "identity-copy",
                "model": None,
                "text": " ".join(segment.get("text", "") for segment in result.segments).strip(),
                "segments": _plain_data(result.segments),
                "raw": None,
                "warnings": [],
            }
            translation_stage.details["method"] = "identity-copy"
            translation_stage.finish(
                StageStatus.SUCCEEDED, tick, self._now, self._monotonic
            )
        else:
            translation_tick = translation_stage.start(self._now, self._monotonic)
            try:
                translated = self.engine.translate(request, profile)
                if not isinstance(translated, Mapping):
                    raise RuntimeError("translation returned a non-mapping result")
                translation_segments, _ = _normalize_segments(
                    translated.get("segments", [])
                )
                translated_text = " ".join(
                    segment.get("text", "") for segment in translation_segments
                ).strip()
                if not translation_segments or not translated_text:
                    raise RuntimeError("translation returned no usable text")
                result.translation = {
                    "status": "succeeded",
                    "source_language": result.source_language,
                    "target_language": request.translation_target,
                    "method": "separate-speech-translation-pass",
                    "model": profile.translation_model,
                    "text": translated_text,
                    "segments": translation_segments,
                    "raw": _plain_data(translated),
                    "warnings": [
                        {
                            "code": "translation_timestamps_not_forced_aligned",
                            "message": (
                                "Translation timestamps are model segment timings; "
                                "translated words were not forced-aligned against "
                                "source-language speech."
                            ),
                        }
                    ],
                }
                translation_stage.details.update(
                    {
                        "model": profile.translation_model,
                        "target_language": request.translation_target,
                        "segment_count": len(translation_segments),
                    }
                )
                translation_stage.finish(
                    StageStatus.SUCCEEDED,
                    translation_tick,
                    self._now,
                    self._monotonic,
                )
            except Exception as exc:
                translation_stage.finish(
                    StageStatus.FAILED,
                    translation_tick,
                    self._now,
                    self._monotonic,
                )
                result.add_error("translation", exc)
                result.translation = {
                    "status": "failed",
                    "source_language": result.source_language,
                    "target_language": request.translation_target,
                    "method": "separate-speech-translation-pass",
                    "model": profile.translation_model,
                    "text": "",
                    "segments": [],
                    "raw": None,
                    "warnings": [],
                    "error": {
                        "type": "ProcessingError",
                        "message": _public_error_message("translation"),
                    },
                }
                result.add_warning(
                    "translation",
                    "source_transcript_preserved",
                    "Translation failed; the source-language transcript remains intact and separate.",
                )
                result.degrade()

        check_cancellation()
        return self._finalize(result, started_at, pipeline_tick)

    def _configuration_failure(
        self,
        request: TranscriptionRequest,
        profile: TranscriptionProfile,
        exc: BaseException,
        started_at: datetime,
        pipeline_tick: float,
    ) -> PipelineResult:
        result = PipelineResult(
            job_id=request.job_id or "invalid-request",
            status=PipelineStatus.FAILED,
            source={"file_name": Path(request.audio_path).name},
            profile=profile.to_dict(),
            stages=[
                StageRecord(name=name, callback=self._stage_callback)
                for name in self.STAGE_NAMES
            ],
            diarization={
                "requested": request.diarize_speakers,
                "status": "skipped",
                "model": None,
                "requested_model": (
                    profile.diarization_model if request.diarize_speakers else None
                ),
                "turns": [],
                "speakers": [],
                "speaker_count": 0,
                "min_speakers_hint": request.min_speakers,
                "max_speakers_hint": request.max_speakers,
                "overlap_regions": [],
            },
            provenance={
                "pipeline_version": PIPELINE_VERSION,
                "created_at": _iso(started_at),
                "request": _request_provenance(request),
            },
        )
        return self._fail_validation(result, exc, started_at, pipeline_tick)

    def _fail_validation(
        self,
        result: PipelineResult,
        exc: BaseException,
        started_at: datetime,
        pipeline_tick: float,
    ) -> PipelineResult:
        stage = result.stage("input_validation")
        tick = stage.start(self._now, self._monotonic)
        stage.finish(StageStatus.FAILED, tick, self._now, self._monotonic)
        result.add_error("input_validation", exc)
        result.status = PipelineStatus.FAILED
        self._skip_after(result, "input_validation", "input validation failed")
        return self._finalize(result, started_at, pipeline_tick)

    def _skip_after(self, result: PipelineResult, stage_name: str, reason: str) -> None:
        found = False
        for stage in result.stages:
            if stage.name == stage_name:
                found = True
                continue
            if found and stage.status is StageStatus.PENDING:
                stage.skip(reason, self._now)

    def _finalize(
        self,
        result: PipelineResult,
        started_at: datetime,
        pipeline_tick: float,
    ) -> PipelineResult:
        completed_at = self._now()
        diarization_stage = result.stage("diarization")
        if (
            result.diarization.get("status") == "pending"
            and diarization_stage.status is StageStatus.SKIPPED
        ):
            # Early validation or source-ASR failures skip all later stages.
            # Keep the structured outcome consistent with the stage record.
            result.diarization["status"] = "skipped"
        engine_provenance = _plain_data(self.engine.provenance())
        if engine_provenance.get("mock") is True:
            result.add_warning(
                "input_validation",
                "mock_output_non_evidentiary",
                "Synthetic mock output was generated without inspecting the media. It must never be used as a transcript or evidentiary work product.",
            )
            result.degrade()
        result.provenance.update(
            {
                "started_at": _iso(started_at),
                "completed_at": _iso(completed_at),
                "duration_ms": max(
                    0, round((self._monotonic() - pipeline_tick) * 1000)
                ),
                "engine": engine_provenance,
                "stage_order": list(self.STAGE_NAMES),
                "source_preserved": (
                    result.stage("source_transcription").status
                    is StageStatus.SUCCEEDED
                    and "source_transcription" in result.raw
                ),
                "translation_is_separate_artifact": True,
                "delivery_only": True,
                "retention_managed_by_job_runner": True,
                # The pipeline reports technical provenance; it does not make a
                # legal admissibility or evidentiary-use determination.
                "evidentiary_output_allowed": False,
                "human_review_required": True,
                "mock_output": engine_provenance.get("mock") is True,
            }
        )
        return result


def _request_provenance(request: TranscriptionRequest) -> dict[str, Any]:
    return {
        "profile": request.profile,
        "requested_language": request.language,
        "translation_target": request.translation_target,
        "diarize_speakers": request.diarize_speakers,
        "min_speakers": request.min_speakers,
        "max_speakers": request.max_speakers,
        "hotwords": list(request.hotwords),
        "alignment_model": request.alignment_model,
        "device": request.device,
        "device_index": request.device_index,
        "local_files_only": request.local_files_only,
    }


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_float(mapping: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        value = _float_or_none(mapping.get(key))
        if value is not None:
            return value
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _normalize_turns(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        start = _float_or_none(row.get("start"))
        end = _float_or_none(row.get("end"))
        if start is None or end is None or end < start:
            continue
        turns.append(
            {
                "id": f"turn_{index + 1:06d}",
                "start": start,
                "end": end,
                "speaker": row.get("speaker") or row.get("label"),
                "confidence": _first_float(
                    row, ("confidence", "score", "probability")
                ),
                "raw": _plain_data(row),
            }
        )
    return sorted(
        turns,
        key=lambda turn: (
            turn["start"],
            turn["end"],
            str(turn.get("speaker") or ""),
            turn["id"],
        ),
    )


def _overlap_regions(turns: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    events: dict[float, list[tuple[str, int]]] = {}
    for turn in turns:
        speaker = str(turn.get("speaker") or "").strip()
        start = _float_or_none(turn.get("start"))
        end = _float_or_none(turn.get("end"))
        if not speaker or start is None or end is None or end <= start:
            continue
        events.setdefault(start, []).append((speaker, 1))
        events.setdefault(end, []).append((speaker, -1))

    active: dict[str, int] = {}
    candidates: list[tuple[float, float, tuple[str, ...]]] = []
    previous: float | None = None
    for timestamp in sorted(events):
        speakers = tuple(sorted(name for name, count in active.items() if count > 0))
        if previous is not None and timestamp > previous and len(speakers) >= 2:
            candidates.append((previous, timestamp, speakers))
        for speaker, delta in events[timestamp]:
            count = active.get(speaker, 0) + delta
            if count > 0:
                active[speaker] = count
            else:
                active.pop(speaker, None)
        previous = timestamp

    # Merge adjacent intervals only when their complete active-speaker set is
    # identical. Three-way overlap therefore becomes one disjoint, inspectable
    # interval rather than several contradictory pairwise records.
    merged: list[list[Any]] = []
    for start, end, speakers in candidates:
        if merged and merged[-1][2] == speakers and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end, speakers])
    return [
        {
            "id": f"overlap_{index + 1:06d}",
            "start": start,
            "end": end,
            "speakers": list(speakers),
        }
        for index, (start, end, speakers) in enumerate(merged)
    ]


def _interval_overlap(
    start: float | None,
    end: float | None,
    overlap_regions: Sequence[Mapping[str, Any]],
    overlap_ends: Sequence[float] | None = None,
) -> tuple[bool, list[str]]:
    if start is None or end is None:
        return False, []
    speakers: set[str] = set()
    first = bisect_right(overlap_ends, start) if overlap_ends is not None else 0
    for region in overlap_regions[first:]:
        if float(region["start"]) >= end:
            break
        if min(end, float(region["end"])) > max(start, float(region["start"])):
            speakers.update(str(value) for value in region.get("speakers", []))
    return bool(speakers), sorted(speakers)


def _normalize_segments(
    raw_segments: Any,
    *,
    turns: Sequence[Mapping[str, Any]] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(raw_segments, Sequence) or isinstance(
        raw_segments, (str, bytes, bytearray)
    ):
        raise RuntimeError("segments must be a sequence")

    overlap_regions = _overlap_regions(turns)
    overlap_ends = [float(region["end"]) for region in overlap_regions]
    segments: list[dict[str, Any]] = []
    flattened_words: list[dict[str, Any]] = []
    word_counter = 0
    for segment_index, raw_segment in enumerate(raw_segments):
        if not isinstance(raw_segment, Mapping):
            continue
        segment_id = f"seg_{segment_index + 1:06d}"
        start = _float_or_none(raw_segment.get("start"))
        end = _float_or_none(raw_segment.get("end"))
        segment_words: list[dict[str, Any]] = []
        raw_words = raw_segment.get("words", [])
        if isinstance(raw_words, Sequence) and not isinstance(
            raw_words, (str, bytes, bytearray)
        ):
            for raw_word in raw_words:
                if not isinstance(raw_word, Mapping):
                    continue
                word_counter += 1
                word_start = _float_or_none(raw_word.get("start"))
                word_end = _float_or_none(raw_word.get("end"))
                is_overlap, overlap_speakers = _interval_overlap(
                    word_start, word_end, overlap_regions, overlap_ends
                )
                word = {
                    "id": f"word_{word_counter:08d}",
                    "segment_id": segment_id,
                    "text": str(raw_word.get("word", raw_word.get("text", ""))),
                    "start": word_start,
                    "end": word_end,
                    "confidence": _first_float(
                        raw_word,
                        ("confidence", "score", "probability", "avg_logprob"),
                    ),
                    "speaker": raw_word.get("speaker") or raw_segment.get("speaker"),
                    "overlap": is_overlap,
                    "overlap_speakers": overlap_speakers,
                    "raw": _plain_data(raw_word),
                }
                segment_words.append(word)
                flattened_words.append(dict(word))

        confidence = _first_float(
            raw_segment, ("confidence", "score", "probability", "avg_logprob")
        )
        word_confidences = [
            float(word["confidence"])
            for word in segment_words
            if word.get("confidence") is not None
        ]
        if confidence is None and word_confidences:
            confidence = sum(word_confidences) / len(word_confidences)
        is_overlap, overlap_speakers = _interval_overlap(
            start, end, overlap_regions, overlap_ends
        )
        segments.append(
            {
                "id": segment_id,
                "start": start,
                "end": end,
                "text": str(raw_segment.get("text", "")).strip(),
                "speaker": raw_segment.get("speaker"),
                "confidence": confidence,
                "overlap": is_overlap,
                "overlap_speakers": overlap_speakers,
                "words": segment_words,
                "raw": _plain_data(raw_segment),
            }
        )
    return segments, flattened_words


def _plain_data(value: Any, _depth: int = 0) -> Any:
    """Convert model outputs to JSON-safe data without importing NumPy/Pandas."""

    if _depth > 50:
        return "<maximum serialization depth reached>"
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, bytes):
        return {"type": "bytes", "length": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if is_dataclass(value) and not isinstance(value, type):
        return _plain_data(asdict(value), _depth + 1)
    if isinstance(value, Mapping):
        return {
            str(key): _plain_data(item, _depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain_data(item, _depth + 1) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain_data(item, _depth + 1) for item in value)

    # NumPy scalar values expose ``item``; keep this intentionally narrow so a
    # tensor/array cannot accidentally expand into a massive provenance payload.
    item_method = getattr(value, "item", None)
    shape = getattr(value, "shape", None)
    if callable(item_method) and shape in (None, ()):
        try:
            return _plain_data(item_method(), _depth + 1)
        except (TypeError, ValueError):
            pass
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _plain_data(to_dict(orient="records"), _depth + 1)
        except TypeError:
            try:
                return _plain_data(to_dict(), _depth + 1)
            except Exception:
                pass
    return {
        "type": f"{type(value).__module__}.{type(value).__qualname__}",
        "value_unavailable": True,
    }


__all__ = [
    "DiarizationOutput",
    "LocalWhisperXEngine",
    "MissingRuntimeDependency",
    "MockPipelineEngine",
    "PipelineConfigurationError",
    "PipelineCancellationRequested",
    "PipelineEngine",
    "PipelineRequest",
    "PipelineResult",
    "PipelineStatus",
    "StageRecord",
    "StageStatus",
    "TranscriptionPipeline",
    "TranscriptionRequest",
    "UnsupportedTranslationError",
    "create_pipeline_engine",
]
