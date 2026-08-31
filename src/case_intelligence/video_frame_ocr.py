"""Bounded, fail-soft contracts for future sampled-frame video OCR.

This module deliberately stops before persistence, retrieval, or user-facing
capability exposure. It gives a decoder/OCR adapter a portable contract with
hard sample, byte, pixel, text, and time budgets while preserving the decoder's
observed presentation timestamp and frame number. A later slice can connect
these results to matter-scoped evidence only after citation, export, and purge
integration is complete.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Callable


MAX_FRAME_SAMPLES = 48
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_FRAME_PIXELS = 16_000_000
MAX_FRAME_TEXT_CHARS = 20_000
MIN_SAMPLE_INTERVAL_MS = 5_000
MAX_SAMPLE_INTERVAL_MS = 10 * 60_000
MAX_STEP_TIMEOUT_SECONDS = 30.0

FRAME_OCR_LIMITATIONS = (
    "Only a bounded sample of video frames is checked; intervening frames are not searched.",
    "Recognized on-screen text is OCR evidence, not identification of people, objects, or events.",
    "Speech remains transcript evidence and is not inferred from sampled frames.",
)

_FAILURE_CATEGORIES = {
    "decode_unavailable",
    "decode_timeout",
    "decode_failed",
    "unsafe_frame",
    "duplicate_frame",
    "ocr_unavailable",
    "ocr_timeout",
    "ocr_failed",
    "ocr_output_too_large",
}


@dataclass(frozen=True)
class FrameOcrPolicy:
    """Resource policy for one source version.

    Callbacks must enforce ``step_timeout_seconds`` at their subprocess or
    service boundary. This coordinator passes the budget and converts a missed
    frame into a content-free failure instead of failing the recording.
    """

    sample_interval_ms: int = 60_000
    max_frames: int = 30
    max_frame_bytes: int = MAX_FRAME_BYTES
    max_frame_pixels: int = MAX_FRAME_PIXELS
    max_text_chars: int = MAX_FRAME_TEXT_CHARS
    step_timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if not MIN_SAMPLE_INTERVAL_MS <= self.sample_interval_ms <= MAX_SAMPLE_INTERVAL_MS:
            raise ValueError("sample interval is outside the safe range")
        if not 1 <= self.max_frames <= MAX_FRAME_SAMPLES:
            raise ValueError("frame sample count is outside the safe range")
        if not 1 <= self.max_frame_bytes <= MAX_FRAME_BYTES:
            raise ValueError("frame byte limit is outside the safe range")
        if not 1 <= self.max_frame_pixels <= MAX_FRAME_PIXELS:
            raise ValueError("frame pixel limit is outside the safe range")
        if not 1 <= self.max_text_chars <= MAX_FRAME_TEXT_CHARS:
            raise ValueError("frame text limit is outside the safe range")
        if not 0 < self.step_timeout_seconds <= MAX_STEP_TIMEOUT_SECONDS:
            raise ValueError("frame step timeout is outside the safe range")


@dataclass(frozen=True)
class DecodedVideoFrame:
    """One bounded frame plus provenance reported by the decoder."""

    requested_time_ms: int
    presentation_time_ms: int
    frame_number: int
    width: int
    height: int
    image_bytes: bytes


@dataclass(frozen=True)
class FrameOcrEvidence:
    """Recognized frame text with an exact, matter-owned source locator."""

    evidence_id: str
    matter_id: str
    document_id: str
    source_version_id: str
    requested_time_ms: int
    presentation_time_ms: int
    frame_number: int
    location: str
    text: str
    evidence_kind: str = "video_frame_ocr"


@dataclass(frozen=True)
class FrameOcrFailure:
    requested_time_ms: int
    category: str

    def __post_init__(self) -> None:
        if self.category not in _FAILURE_CATEGORIES:
            raise ValueError("unknown frame OCR failure category")


@dataclass(frozen=True)
class FrameOcrResult:
    state: str
    planned_frame_count: int
    decoded_frame_count: int
    evidence: tuple[FrameOcrEvidence, ...]
    failures: tuple[FrameOcrFailure, ...]
    limitations: tuple[str, ...] = FRAME_OCR_LIMITATIONS

    @property
    def searchable(self) -> bool:
        """Always false until persistence and exact citation resolution land."""

        return False


class FrameOcrStepError(RuntimeError):
    """Content-free adapter failure safe to retain in processing telemetry."""

    def __init__(self, category: str):
        if category not in _FAILURE_CATEGORIES:
            raise ValueError("unknown frame OCR failure category")
        super().__init__(category)
        self.category = category


FrameDecoder = Callable[..., DecodedVideoFrame]
FrameRecognizer = Callable[..., str]


def plan_sample_times(
    duration_ms: int, *, policy: FrameOcrPolicy = FrameOcrPolicy()
) -> tuple[int, ...]:
    """Return deterministic, timeline-spread seek targets without large ranges."""

    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms <= 0:
        raise ValueError("video duration must be a positive integer number of milliseconds")
    last_ms = duration_ms - 1
    nominal_count = max(1, math.ceil(duration_ms / policy.sample_interval_ms))
    if nominal_count <= policy.max_frames:
        points = [index * policy.sample_interval_ms for index in range(nominal_count)]
        if points[-1] != last_ms and len(points) < policy.max_frames:
            points.append(last_ms)
        return tuple(dict.fromkeys(min(point, last_ms) for point in points))
    if policy.max_frames == 1:
        return (0,)
    # Spread a capped sample across the whole recording instead of silently
    # checking only its beginning.
    return tuple(
        round(index * last_ms / (policy.max_frames - 1))
        for index in range(policy.max_frames)
    )


def _opaque_identifier(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 160 or any(ord(char) < 32 for char in normalized):
        raise ValueError(f"{label} is invalid")
    return normalized


def _timestamp(value_ms: int) -> str:
    hours, remainder = divmod(value_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _recognized_text(value: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise FrameOcrStepError("ocr_failed")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()
    normalized = re.sub(r"[\t ]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    if len(normalized) > maximum:
        raise FrameOcrStepError("ocr_output_too_large")
    return normalized


def run_sampled_frame_ocr(
    *,
    matter_id: str,
    document_id: str,
    source_version_id: str,
    duration_ms: int,
    decode_frame: FrameDecoder,
    recognize_frame: FrameRecognizer,
    policy: FrameOcrPolicy = FrameOcrPolicy(),
) -> FrameOcrResult:
    """Run a bounded adapter contract and return exact, non-searchable evidence.

    Callback exception messages are intentionally discarded. Adapters should
    raise :class:`FrameOcrStepError` for a known category and must never place
    source text, paths, command lines, or host details in that category.
    """

    matter = _opaque_identifier(matter_id, "matter identity")
    document = _opaque_identifier(document_id, "document identity")
    version = _opaque_identifier(source_version_id, "source version identity")
    planned = plan_sample_times(duration_ms, policy=policy)
    evidence: list[FrameOcrEvidence] = []
    failures: list[FrameOcrFailure] = []
    observed: set[tuple[int, int]] = set()
    decoded_count = 0

    for requested_ms in planned:
        try:
            frame = decode_frame(
                requested_ms, timeout_seconds=policy.step_timeout_seconds
            )
        except FrameOcrStepError as exc:
            failures.append(FrameOcrFailure(requested_ms, exc.category))
            continue
        except TimeoutError:
            failures.append(FrameOcrFailure(requested_ms, "decode_timeout"))
            continue
        except OSError:
            failures.append(FrameOcrFailure(requested_ms, "decode_unavailable"))
            continue
        except Exception:
            failures.append(FrameOcrFailure(requested_ms, "decode_failed"))
            continue

        if (
            not isinstance(frame, DecodedVideoFrame)
            or frame.requested_time_ms != requested_ms
            or not 0 <= frame.presentation_time_ms < duration_ms
            or frame.frame_number < 0
            or frame.width <= 0
            or frame.height <= 0
            or frame.width * frame.height > policy.max_frame_pixels
            or not isinstance(frame.image_bytes, bytes)
            or not 0 < len(frame.image_bytes) <= policy.max_frame_bytes
        ):
            failures.append(FrameOcrFailure(requested_ms, "unsafe_frame"))
            continue
        decoded_count += 1
        provenance = (frame.presentation_time_ms, frame.frame_number)
        if provenance in observed:
            failures.append(FrameOcrFailure(requested_ms, "duplicate_frame"))
            continue
        observed.add(provenance)

        try:
            text = _recognized_text(
                recognize_frame(
                    frame.image_bytes,
                    timeout_seconds=policy.step_timeout_seconds,
                ),
                maximum=policy.max_text_chars,
            )
        except FrameOcrStepError as exc:
            failures.append(FrameOcrFailure(requested_ms, exc.category))
            continue
        except TimeoutError:
            failures.append(FrameOcrFailure(requested_ms, "ocr_timeout"))
            continue
        except OSError:
            failures.append(FrameOcrFailure(requested_ms, "ocr_unavailable"))
            continue
        except Exception:
            failures.append(FrameOcrFailure(requested_ms, "ocr_failed"))
            continue
        if not text:
            continue

        digest = hashlib.sha256(
            f"{version}\0{frame.presentation_time_ms}\0{frame.frame_number}".encode("utf-8")
        ).hexdigest()[:24]
        evidence.append(
            FrameOcrEvidence(
                evidence_id=f"video-frame-{digest}",
                matter_id=matter,
                document_id=document,
                source_version_id=version,
                requested_time_ms=requested_ms,
                presentation_time_ms=frame.presentation_time_ms,
                frame_number=frame.frame_number,
                location=(
                    f"video frame {_timestamp(frame.presentation_time_ms)} "
                    f"(frame {frame.frame_number})"
                ),
                text=text,
            )
        )

    if evidence and failures:
        state = "partial"
    elif evidence:
        state = "ready"
    elif failures:
        state = "unavailable"
    else:
        state = "no_text"
    return FrameOcrResult(
        state=state,
        planned_frame_count=len(planned),
        decoded_frame_count=decoded_count,
        evidence=tuple(evidence),
        failures=tuple(failures),
    )
