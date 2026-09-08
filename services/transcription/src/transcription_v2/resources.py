"""Host-resource checks and cooperative GPU admission control."""

from __future__ import annotations

import contextlib
import fcntl
import importlib.metadata
import os
import shutil
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from .settings import Settings


PINNED_WHISPERX_VERSION = "3.8.6"


@dataclass(frozen=True, slots=True)
class GpuState:
    index: int
    name: str
    total_vram_mb: int
    free_vram_mb: int
    utilization_percent: int


def gpu_states() -> list[GpuState]:
    """Read GPU capacity without importing torch or initializing CUDA."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    states: list[GpuState] = []
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            continue
        try:
            states.append(
                GpuState(
                    index=int(fields[0]),
                    name=fields[1],
                    total_vram_mb=int(fields[2]),
                    free_vram_mb=int(fields[3]),
                    utilization_percent=int(fields[4]),
                )
            )
        except ValueError:
            continue
    return states


def _whisperx_runtime_checks() -> tuple[bool, bool, str | None]:
    """Inspect the pinned package and bundled VAD without importing ML code."""

    try:
        distribution = importlib.metadata.distribution("whisperx")
    except importlib.metadata.PackageNotFoundError:
        return False, False, None
    version = distribution.version
    vad_asset = Path(
        distribution.locate_file("whisperx/assets/pytorch_model.bin")
    )
    return version == PINNED_WHISPERX_VERSION, vad_asset.is_file(), version


def _manifest_file_present(settings: Settings) -> bool:
    """Check only the safe manifest location; the worker/CLI perform hashing."""

    manifest = settings.approved_model_manifest_path
    try:
        manifest.resolve(strict=False).relative_to(
            settings.model_cache_dir.resolve(strict=False)
        )
        manifest_status = os.lstat(manifest)
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(manifest_status.st_mode) and not stat.S_ISLNK(
        manifest_status.st_mode
    )


def _diarization_config_present(configured_path: Path | None) -> bool:
    if configured_path is None:
        return False
    candidate = (
        configured_path
        if configured_path.is_file()
        else configured_path / "config.yaml"
    )
    return candidate.is_file()


def readiness(settings: Settings) -> dict[str, object]:
    usage = shutil.disk_usage(settings.data_root)
    gpus = gpu_states() if settings.inference_device == "cuda" else []
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    reserved_index = int(visible) if visible.isdigit() else None
    reserved_gpu = next(
        (gpu for gpu in gpus if gpu.index == reserved_index),
        None,
    )
    diarization_path_value = os.environ.get(
        "TRANSCRIPTION_V2_DIARIZATION_MODEL_PATH", ""
    ).strip()
    diarization_path = Path(diarization_path_value) if diarization_path_value else None
    whisperx_version_ok, packaged_vad_present, whisperx_version = (
        _whisperx_runtime_checks()
    )
    checks: dict[str, object] = {
        "data_root_writable": (
            settings.data_root.is_dir()
            and os.access(settings.data_root, os.W_OK | os.X_OK)
        ),
        "free_disk_bytes": usage.free,
        "minimum_free_disk_bytes": settings.minimum_free_disk_bytes,
        "disk_admission_ready": usage.free >= settings.minimum_free_disk_bytes,
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "ffprobe_available": shutil.which("ffprobe") is not None,
        "pipeline_backend": settings.pipeline_backend,
        "inference_device": settings.inference_device,
        "gpu_required": settings.pipeline_backend == "whisperx" and settings.inference_device == "cuda",
        "model_manifest_required": settings.pipeline_backend == "whisperx",
        "model_manifest_present": _manifest_file_present(settings),
        "model_manifest_integrity_gate": "worker_start_and_verify_models_cli",
        "gpus": [asdict(gpu) for gpu in gpus],
        "reserved_gpu_index": reserved_index,
        "reserved_gpu_ready": bool(
            reserved_gpu
            and reserved_gpu.free_vram_mb >= settings.minimum_free_vram_mb
        ),
        "model_cache_present": settings.model_cache_dir.is_dir(),
        "diarization_model_present": _diarization_config_present(
            diarization_path
        ),
        "whisperx_version": whisperx_version,
        "whisperx_version_compatible": whisperx_version_ok,
        "packaged_vad_present": packaged_vad_present,
        "offline_runtime": all(
            os.environ.get(name, "").strip() == "1"
            for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
        ),
    }
    if settings.pipeline_backend == "mock":
        ready = bool(checks["data_root_writable"] and checks["disk_admission_ready"])
        status = "ready" if ready else "not_ready"
    else:
        base_ready = bool(
            checks["data_root_writable"]
            and checks["disk_admission_ready"]
            and checks["ffmpeg_available"]
            and checks["ffprobe_available"]
            and (settings.inference_device == "cpu" or checks["reserved_gpu_ready"])
            and checks["model_cache_present"]
            and checks["model_manifest_present"]
            and checks["whisperx_version_compatible"]
            and checks["packaged_vad_present"]
            and checks["offline_runtime"]
        )
        if base_ready and checks["diarization_model_present"]:
            status = "ready"
        elif base_ready and settings.allow_degraded_diarization:
            status = "degraded_ready"
        else:
            status = "not_ready"
    checks["degraded_diarization_allowed"] = settings.allow_degraded_diarization
    return {"status": status, "checks": checks}


@contextlib.contextmanager
def gpu_reservation(lock_path: Path) -> Iterator[None]:
    """Acquire the cooperative host GPU lock for one whole pipeline run.

    This protects workers configured to share the lock. Other GPU consumers
    require an exclusive device assignment or a scheduler that coordinates
    every participating process.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
