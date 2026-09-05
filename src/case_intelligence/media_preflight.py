"""Bounded, offline recording inspection; never trims or transcribes a source."""
from __future__ import annotations

import array
import math
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from .pilot_uploads import UploadProblem, _probe_media

REVISION = "webrtcvad-2.0.14-mode3-30ms-v1"
MAX_SECONDS = 600
MAX_WALL_SECONDS = 60
FRAME_MS = 30
FRAME_BYTES = 960

MESSAGES = {
    "no_audio": "This video has no audio track. It is available for playback without transcription.",
    "no_speech": "No speech was detected. Listen to the recording before deciding whether to transcribe it.",
    "uncertain": "The speech check is uncertain. Listen to the recording, then transcribe or check again.",
    "failed": "The recording check did not finish. Try the check again; playback remains available.",
    "ready": "Likely speech found. The original recording is ready for transcription.",
}


def inspect_recording(
    source: Path, media_type: str, *, cancelled: Callable[[], bool] = lambda: False
) -> dict[str, object]:
    """Inspect at most ten minutes, with original-time offsets and bounded memory.

    VAD is only a likely-speech hint. No language or intelligibility inference is
    made. A partial check can never establish absence across a whole recording.
    """
    result: dict[str, object] = {
        "revision": REVISION, "outcome": "failed", "complete": False,
        "checked_ms": 0, "first_speech_ms": None, "last_speech_ms": None,
        "quiet_ms": 0, "leading_quiet_ms": 0, "trailing_quiet_ms": 0,
        "language": "not_assessed", "quality": [],
    }
    try:
        probe = _probe_media(source, media_type)
    except UploadProblem:
        return result
    if not probe.has_audio:
        result.update(outcome="no_audio", complete=True)
        return result
    try:
        import webrtcvad
        if getattr(webrtcvad, "__version__", None) != "2.0.14":
            result.update(outcome="uncertain", quality=["check_unavailable"])
            return result
        detector = webrtcvad.Vad(3)
    except (ImportError, OSError):
        result.update(outcome="uncertain", quality=["check_unavailable"])
        return result
    command = [
        "/usr/bin/ffmpeg", "-nostdin", "-v", "error", "-threads", "1",
        "-protocol_whitelist", "file,pipe", "-i", str(source),
        "-map", "0:a:0", "-vn", "-t", str(MAX_SECONDS),
        "-af", "aresample=async=1:first_pts=0", "-ac", "1", "-ar", "16000",
        "-f", "s16le", "pipe:1",
    ]
    process = None
    frames = quiet = trailing = leading = voiced = run = longest = clipped = samples = 0
    energy = 0
    stopped = False
    pending = b""
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        )
        assert process.stdout is not None
        deadline = time.monotonic() + MAX_WALL_SECONDS
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while frames * FRAME_MS < MAX_SECONDS * 1000:
                if cancelled() or time.monotonic() >= deadline:
                    stopped = True
                    break
                if not selector.select(timeout=0.2):
                    continue
                chunk = process.stdout.read1(64 * 1024)
                if not chunk:
                    break
                pending += chunk
                while len(pending) >= FRAME_BYTES:
                    frame, pending = pending[:FRAME_BYTES], pending[FRAME_BYTES:]
                    values = array.array("h", frame)
                    if sys.byteorder != "little":
                        values.byteswap()
                    square_sum = sum(value * value for value in values)
                    rms = math.sqrt(square_sum / len(values))
                    energy += square_sum
                    samples += len(values)
                    clipped += sum(abs(value) >= 32700 for value in values)
                    is_quiet = rms < 33  # approximately -60 dBFS, a level fact only
                    quiet += int(is_quiet)
                    trailing = trailing + 1 if is_quiet else 0
                    if quiet == frames + 1:
                        leading += 1
                    speech = detector.is_speech(frame, 16000)
                    if speech:
                        voiced += 1
                        run += 1
                        longest = max(longest, run)
                        if run >= 10:
                            if result["first_speech_ms"] is None:
                                result["first_speech_ms"] = (frames + 1 - run) * FRAME_MS
                            result["last_speech_ms"] = (frames + 1) * FRAME_MS
                    else:
                        run = 0
                    frames += 1
        if stopped:
            process.kill()
        returncode = process.wait(timeout=5)
        if returncode and not stopped:
            return result
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return result
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
    decoded_ms = frames * FRAME_MS
    checked = min(decoded_ms, probe.duration_ms)
    complete = (not stopped and probe.duration_ms <= MAX_SECONDS * 1000
                and abs(decoded_ms - probe.duration_ms) < 100 and probe.audio_track_count == 1)
    quality = []
    if probe.audio_track_count > 1:
        quality.append("multiple_audio_tracks")
    if not complete:
        quality.append("partial_check")
    rms = math.sqrt(energy / samples) if samples else 0
    if 0 < rms < 328:
        quality.append("low_volume")
    if samples and clipped / samples > 0.01:
        quality.append("clipping")
    outcome = "uncertain"
    if complete and frames and quiet / frames >= 0.99 and voiced == 0 and not quality:
        outcome = "no_speech"
    elif complete and longest >= 10 and voiced >= 20 and not quality:
        outcome = "ready"
    result.update(
        outcome=outcome, complete=complete, checked_ms=checked,
        quiet_ms=quiet * FRAME_MS, leading_quiet_ms=leading * FRAME_MS,
        trailing_quiet_ms=trailing * FRAME_MS, quality=quality,
    )
    return result
