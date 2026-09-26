"""Bounded, offline subprocess contract for the separate Nemotron runtime."""
from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

MODEL_ID = "nvidia/Nemotron-3-Diarization"
MODEL_REVISION = "0f087031414a6616bda8228f447d915a70a25720"
MODEL_LICENSE = "OpenMDW-1.1"
RUNTIME_REVISION = "002e1edf5b5198488297f401dd853056b6521d02"
MODEL_FILES = ("config.json", "processor_config.json", "model.safetensors")
MAX_RESULT_BYTES = 4 * 1024 * 1024
MAX_TURNS = 50_000


class NemotronError(RuntimeError):
    """Content-free adapter failure; dependency stderr is never delivered."""


def validate_turns(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > MAX_TURNS:
        raise NemotronError("Invalid Nemotron result")
    turns = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {"start", "end", "speaker"}:
            raise NemotronError("Invalid Nemotron turn")
        start, end, speaker = row["start"], row["end"], row["speaker"]
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start
                or type(speaker) is not int or not 0 <= speaker < 8):
            raise NemotronError("Invalid Nemotron turn")
        turns.append({"start": float(start), "end": float(end),
                      "speaker": f"SPEAKER_{speaker:02d}"})
    # Preserve concurrent speakers; sorting must never make turns exclusive.
    return sorted(turns, key=lambda row: (row["start"], row["end"], row["speaker"]))


def approved_snapshot(path, *, cache_root, model_readiness) -> bool:
    if not path:
        return False
    root = Path(path)
    try:
        for filename in MODEL_FILES:
            target = root / filename
            target.resolve(strict=True).relative_to(Path(cache_root).resolve(strict=True))
            if not model_readiness.authorizes_file(
                    target, role="diarization", model_id=MODEL_ID, revision=MODEL_REVISION):
                return False
        return True
    except (OSError, ValueError):
        return False


def run_diarization(*, python: str, model_path: str, audio_path: str,
                    device: str, timeout_seconds: float = 3600,
                    cancel_requested: Callable[[], bool] | None = None,
                    gpu_memory_fraction: float = 0.25) -> list[dict[str, object]]:
    """Use stdin for private paths and a size-limited temporary output file.

    Only the fixed runner path appears in process arguments. On timeout,
    cancellation, malformed output or any other exit, reap the entire child
    process group. The caller must authorize the staged model manifest first.
    """
    if (not math.isfinite(timeout_seconds) or timeout_seconds <= 0
            or not math.isfinite(gpu_memory_fraction) or not 0 < gpu_memory_fraction <= 1):
        raise ValueError("Invalid Nemotron resource limit")
    if not Path(python).is_absolute() or not os.access(python, os.X_OK):
        raise NemotronError("Nemotron runtime is unavailable")
    # Do not inherit hub tokens, proxy credentials or arbitrary Python settings.
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "HOME", "TMPDIR", "CUDA_VISIBLE_DEVICES", "LD_LIBRARY_PATH"}}
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1",
               OMP_NUM_THREADS="1", TOKENIZERS_PARALLELISM="false")
    payload = json.dumps({"model_path": model_path, "audio_path": audio_path,
                          "device": device, "gpu_memory_fraction": gpu_memory_fraction}).encode()
    if len(payload) > 16_384:
        raise NemotronError("Invalid Nemotron request")
    runner = Path(__file__).with_name("nemotron_runner.py")
    with (tempfile.TemporaryDirectory(prefix="recordbench-nemotron-") as scratch,
          tempfile.TemporaryFile() as input_file, tempfile.TemporaryFile() as output):
        env.update(NUMBA_CACHE_DIR=str(Path(scratch) / "numba"),
                   HF_HOME=str(Path(scratch) / "huggingface"),
                   XDG_CACHE_HOME=str(Path(scratch) / "cache"),
                   TORCH_HOME=str(Path(scratch) / "torch"))
        input_file.write(payload)
        input_file.seek(0)
        child = subprocess.Popen([python, "-I", str(runner)], stdin=input_file,
                                 stdout=output, stderr=subprocess.DEVNULL,
                                 env=env, start_new_session=True)
        try:
            deadline = time.monotonic() + timeout_seconds
            while True:
                if cancel_requested is not None and cancel_requested():
                    raise NemotronError("Nemotron processing canceled")
                if os.fstat(output.fileno()).st_size > MAX_RESULT_BYTES:
                    raise NemotronError("Nemotron result exceeds size limit")
                if child.poll() is not None:
                    break
                if time.monotonic() >= deadline:
                    raise NemotronError("Nemotron processing timed out")
                time.sleep(0.05)
            if child.returncode:
                raise NemotronError("Nemotron processing failed")
            output.seek(0)
            raw = output.read(MAX_RESULT_BYTES + 1)
            if len(raw) > MAX_RESULT_BYTES:
                raise NemotronError("Nemotron result exceeds size limit")
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeError):
                raise NemotronError("Invalid Nemotron result") from None
            if (not isinstance(result, dict) or set(result) != {"schema", "turns"}
                    or result["schema"] != "recordbench-nemotron-v1"):
                raise NemotronError("Invalid Nemotron result")
            return validate_turns(result["turns"])
        finally:
            # The process group also covers decoder descendants after an early
            # parent exit. Never leave a detached inference process using VRAM.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
