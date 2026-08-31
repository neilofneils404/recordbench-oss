"""Media validation and probing without loading recordings into memory."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SUPPORTED_EXTENSIONS = frozenset(
    {
        ".aac",
        ".avi",
        ".flac",
        ".m4a",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".oga",
        ".ogg",
        ".opus",
        ".wav",
        ".webm",
        ".wma",
        ".wmv",
    }
)


class MediaProbeError(RuntimeError):
    """The file could not be safely recognized as audio/video media."""


class MediaDurationExceeded(MediaProbeError):
    """The recording is valid media but exceeds the processing duration limit."""


@dataclass(frozen=True, slots=True)
class MediaProbe:
    duration_seconds: float
    audio_streams: int
    channels: int
    sample_rate_hz: int | None
    format_name: str
    has_video: bool
    bit_rate: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_media_name(filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise MediaProbeError(f"Unsupported media extension: {suffix or '(none)'}")


def probe_media(
    path: Path,
    *,
    timeout_seconds: int = 30,
    max_duration_seconds: float | None = None,
) -> MediaProbe:
    """Inspect media using ffprobe and return non-content metadata.

    ffprobe receives an explicit path and no shell is involved. Its output is
    bounded by the subprocess timeout and parsed as JSON.
    """

    validate_media_name(path.name)
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,format_name,bit_rate:stream=codec_type,channels,sample_rate",
                "-of",
                "json",
                "--",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise MediaProbeError("ffprobe is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaProbeError("Media inspection timed out") from exc

    if completed.returncode != 0:
        # ffprobe output may contain filesystem details, so it is not reflected
        # into an API error or persisted event.
        raise MediaProbeError("The upload is not readable media")
    try:
        payload = json.loads(completed.stdout)
        streams = payload.get("streams") or []
        audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if not audio:
            raise MediaProbeError("The upload contains no audio stream")
        video = any(stream.get("codec_type") == "video" for stream in streams)
        fmt = payload.get("format") or {}
        duration = float(fmt.get("duration") or 0.0)
        if duration <= 0:
            raise MediaProbeError("The upload has no measurable duration")
        if max_duration_seconds is not None and duration > max_duration_seconds:
            raise MediaDurationExceeded("The upload exceeds the media duration limit")
        channels = max(int(stream.get("channels") or 0) for stream in audio)
        sample_rates = [int(stream["sample_rate"]) for stream in audio if stream.get("sample_rate")]
        bit_rate = int(fmt["bit_rate"]) if fmt.get("bit_rate") else None
        return MediaProbe(
            duration_seconds=round(duration, 3),
            audio_streams=len(audio),
            channels=channels,
            sample_rate_hz=max(sample_rates) if sample_rates else None,
            format_name=str(fmt.get("format_name") or "unknown"),
            has_video=video,
            bit_rate=bit_rate,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaProbeError("Media inspection returned invalid metadata") from exc
