"""Durable domain types for the isolated transcription v2 service.

The module is deliberately dependency-free.  Values written to SQLite are
explicit enums so workers, APIs, and UIs share one stable state vocabulary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class JobStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PipelineStage(str, Enum):
    INGEST = "ingest"
    PROBE = "probe"
    TRANSCRIBE = "transcribe"
    ALIGN = "align"
    DIARIZE = "diarize"
    IDENTIFY = "identify"
    TRANSLATE = "translate"
    QUALITY_CONTROL = "quality_control"
    EXPORT = "export"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELED = "canceled"


class EventType(str, Enum):
    """Content-free audit events.

    Events intentionally have no free-form message or payload field.  In
    particular, transcript and audio-derived content must never be copied into
    the event table.
    """

    JOB_CREATED = "job_created"
    FILE_REGISTERED = "file_registered"
    JOB_QUEUED = "job_queued"
    JOB_CLAIMED = "job_claimed"
    STAGE_CHANGED = "stage_changed"
    CANCEL_REQUESTED = "cancel_requested"
    JOB_CANCELED = "job_canceled"
    JOB_SUCCEEDED = "job_succeeded"
    ATTEMPT_FAILED = "attempt_failed"
    JOB_FAILED = "job_failed"
    RETRY_QUEUED = "retry_queued"
    RECOVERED_REQUEUED = "recovered_requeued"
    RECOVERED_FAILED = "recovered_failed"
    SEGMENT_CREATED = "segment_created"
    SEGMENTS_REPLACED = "segments_replaced"
    SEGMENT_UPDATED = "segment_updated"
    SPEAKER_MAPPING_SET = "speaker_mapping_set"


class IdentityStatus(str, Enum):
    UNKNOWN = "unknown"
    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"


class IdentityMethod(str, Enum):
    NONE = "none"
    METADATA = "metadata"
    VOICEPRINT = "voiceprint"
    CONTEXT = "context"
    MANUAL = "manual"


class RecordingType(str, Enum):
    GENERAL = "general"
    JAIL_CALL = "jail_call"
    BODY_CAMERA = "body_camera"
    INTERVIEW = "interview"
    COURT = "court"
    MEETING = "meeting"
    TELEPHONE = "telephone"
    OTHER = "other"


_ISO_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}$")
_BATCH_ID_RE = re.compile(r"^batch_[a-f0-9]{32}$")


def validate_batch_id(value: str) -> str:
    """Validate the opaque server-generated identifier used to group uploads."""

    if not isinstance(value, str) or not _BATCH_ID_RE.fullmatch(value):
        raise ValueError("batch_id is invalid")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list or tuple of strings")
    if len(value) > 500:
        raise ValueError(f"{field_name} cannot contain more than 500 entries")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings")
        item = item.strip()
        if not item:
            continue
        if len(item) > 500:
            raise ValueError(f"{field_name} entries cannot exceed 500 characters")
        normalized.append(item)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class TranscriptionOptions:
    """Validated, versioned request configuration persisted with a job."""

    source_language: str = "auto"
    translate_to_english: bool = False
    recording_type: RecordingType = RecordingType.GENERAL
    min_speakers: int | None = None
    max_speakers: int | None = None
    hotwords: tuple[str, ...] = ()
    glossary: tuple[str, ...] = ()
    roster: tuple[str, ...] = ()
    retention_hours: int = 4
    diarize_speakers: bool = True
    # Internal submission metadata. The API generates this value; callers may
    # not choose it. Keeping it in the existing versioned options JSON avoids a
    # state-schema migration while legacy rows (where it is absent) still load.
    batch_id: str | None = None

    def __post_init__(self) -> None:
        language = str(self.source_language or "auto").strip().lower()
        if language != "auto" and not _ISO_LANGUAGE_RE.fullmatch(language):
            raise ValueError("source_language must be 'auto' or a 2/3-letter ISO code")
        object.__setattr__(self, "source_language", language)

        if not isinstance(self.translate_to_english, bool):
            raise ValueError("translate_to_english must be a boolean")
        if not isinstance(self.diarize_speakers, bool):
            raise ValueError("diarize_speakers must be a boolean")
        if self.batch_id is not None:
            object.__setattr__(self, "batch_id", validate_batch_id(self.batch_id))
        if not isinstance(self.recording_type, RecordingType):
            try:
                object.__setattr__(self, "recording_type", RecordingType(self.recording_type))
            except (TypeError, ValueError) as exc:
                raise ValueError("unsupported recording_type") from exc

        for field_name in ("min_speakers", "max_speakers"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
                raise ValueError(f"{field_name} must be a positive integer or None")
        if (
            self.min_speakers is not None
            and self.max_speakers is not None
            and self.min_speakers > self.max_speakers
        ):
            raise ValueError("min_speakers cannot exceed max_speakers")

        object.__setattr__(self, "hotwords", _string_tuple(self.hotwords, "hotwords"))
        object.__setattr__(self, "glossary", _string_tuple(self.glossary, "glossary"))
        object.__setattr__(self, "roster", _string_tuple(self.roster, "roster"))
        if (
            not isinstance(self.retention_hours, int)
            or isinstance(self.retention_hours, bool)
            or not 1 <= self.retention_hours <= 24
        ):
            raise ValueError("retention_hours must be between 1 and 24")

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": 1,
            "source_language": self.source_language,
            "translate_to_english": self.translate_to_english,
            "diarize_speakers": self.diarize_speakers,
            "recording_type": self.recording_type.value,
            "min_speakers": self.min_speakers,
            "max_speakers": self.max_speakers,
            "hotwords": list(self.hotwords),
            "glossary": list(self.glossary),
            "roster": list(self.roster),
            "retention_hours": self.retention_hours,
        }
        if self.batch_id is not None:
            value["batch_id"] = self.batch_id
        return value

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TranscriptionOptions":
        allowed = {
            "schema_version",
            "source_language",
            "translate_to_english",
            "diarize_speakers",
            "recording_type",
            "min_speakers",
            "max_speakers",
            "hotwords",
            "glossary",
            "roster",
            "retention_hours",
            "batch_id",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown transcription option(s): {', '.join(sorted(unknown))}")
        if value.get("schema_version", 1) != 1:
            raise ValueError("unsupported transcription options schema_version")
        kwargs = {key: item for key, item in value.items() if key != "schema_version"}
        return cls(**kwargs)

    @classmethod
    def from_json(cls, value: str) -> "TranscriptionOptions":
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid transcription options JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError("transcription options JSON must contain an object")
        return cls.from_mapping(decoded)


TERMINAL_JOB_STATUSES = frozenset(
    {JobStatus.CANCELED, JobStatus.SUCCEEDED, JobStatus.FAILED}
)


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    owner_key: str
    status: JobStatus
    stage: PipelineStage
    stage_status: StageStatus
    profile: str
    priority: int
    attempt: int
    max_attempts: int
    available_at: str
    worker_id: str | None
    claimed_at: str | None
    heartbeat_at: str | None
    cancel_requested_at: str | None
    started_at: str | None
    finished_at: str | None
    error_code: str | None
    options: TranscriptionOptions
    expires_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class JobFile:
    id: str
    job_id: str
    original_name: str
    safe_name: str
    relative_path: str
    media_type: str | None
    size_bytes: int
    sha256: str
    created_at: str


@dataclass(frozen=True, slots=True)
class JobEvent:
    sequence: int
    job_id: str
    event_type: EventType
    stage: PipelineStage | None
    job_status: JobStatus | None
    stage_status: StageStatus | None
    worker_id: str | None
    reason_code: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    id: str
    job_id: str
    file_id: str
    ordinal: int
    start_ms: int
    end_ms: int
    speaker_key: str | None
    model_text: str
    edited_text: str | None
    translated_text: str | None
    confidence: float | None
    overlap: bool
    revision: int
    created_at: str
    updated_at: str

    @property
    def text(self) -> str:
        """Human-edited text when present, otherwise immutable model output."""

        return self.model_text if self.edited_text is None else self.edited_text


@dataclass(frozen=True, slots=True)
class SegmentDraft:
    ordinal: int
    start_ms: int
    end_ms: int
    model_text: str
    speaker_key: str | None = None
    translated_text: str | None = None
    confidence: float | None = None
    overlap: bool = False


@dataclass(frozen=True, slots=True)
class SpeakerMapping:
    job_id: str
    speaker_key: str
    display_name: str
    identity_status: IdentityStatus
    identity_method: IdentityMethod
    confidence: float | None
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class RecoverySummary:
    requeued: int = 0
    canceled: int = 0
    failed: int = 0


class StoreError(RuntimeError):
    """Base exception for durable-store failures."""


class NotFoundError(StoreError):
    """Requested durable entity does not exist."""


class InvalidTransitionError(StoreError):
    """Requested state transition is not valid for the current state."""


class ConcurrencyConflictError(StoreError):
    """Optimistic revision or queue ownership no longer matches."""


class RetryLimitError(StoreError):
    """The job has no execution attempts remaining."""
