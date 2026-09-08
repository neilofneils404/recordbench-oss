"""Environment-driven settings for the isolated v2 service.

Defaults are deliberately safe for development: loopback only and a mock
pipeline. Enabling GPU inference is an explicit operator action.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .model_manifest import DEFAULT_MODEL_MANIFEST_NAME


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_MAX_API_TOKEN_FILE_BYTES = 4096


def _validate_api_token(token: str) -> str:
    if token and (
        len(token) < 32
        or token.lower().startswith("replace-with")
        or any(character in "\r\n\x00" for character in token)
    ):
        raise ValueError(
            "TRANSCRIPTION_V2_API_TOKEN must be a non-placeholder secret of at least 32 characters"
        )
    return token


def _read_private_token_file(path: Path) -> str:
    """Read one bounded token without following the configured file symlink."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        path_status = os.lstat(path)
    except OSError:
        raise ValueError("TRANSCRIPTION_V2_API_TOKEN_FILE cannot be read safely") from None
    if stat.S_ISLNK(path_status.st_mode) or not stat.S_ISREG(path_status.st_mode):
        raise ValueError(
            "TRANSCRIPTION_V2_API_TOKEN_FILE must be a regular non-symlink file"
        )
    if stat.S_IMODE(path_status.st_mode) != 0o600:
        raise ValueError("TRANSCRIPTION_V2_API_TOKEN_FILE must have mode 0600")
    if path_status.st_size > _MAX_API_TOKEN_FILE_BYTES:
        raise ValueError("TRANSCRIPTION_V2_API_TOKEN_FILE exceeds its size limit")

    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise ValueError("TRANSCRIPTION_V2_API_TOKEN_FILE cannot be read safely") from None
    try:
        opened_status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_status.st_mode)
            or stat.S_IMODE(opened_status.st_mode) != 0o600
            or (opened_status.st_dev, opened_status.st_ino)
            != (path_status.st_dev, path_status.st_ino)
        ):
            raise ValueError("TRANSCRIPTION_V2_API_TOKEN_FILE changed during validation")
        chunks: list[bytes] = []
        remaining = _MAX_API_TOKEN_FILE_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        final_status = os.fstat(descriptor)
        if (
            len(content) > _MAX_API_TOKEN_FILE_BYTES
            or final_status.st_size != len(content)
            or (
                opened_status.st_dev,
                opened_status.st_ino,
                opened_status.st_size,
                opened_status.st_mtime_ns,
                opened_status.st_ctime_ns,
            )
            != (
                final_status.st_dev,
                final_status.st_ino,
                final_status.st_size,
                final_status.st_mtime_ns,
                final_status.st_ctime_ns,
            )
        ):
            raise ValueError("TRANSCRIPTION_V2_API_TOKEN_FILE changed during validation")
    except OSError:
        raise ValueError("TRANSCRIPTION_V2_API_TOKEN_FILE cannot be read safely") from None
    finally:
        os.close(descriptor)
    try:
        token = content.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise ValueError("TRANSCRIPTION_V2_API_TOKEN_FILE must contain UTF-8 text") from None
    return _validate_api_token(token)


def load_api_token_from_env() -> str:
    """Load the API token from one unambiguous environment source.

    Token values and configured paths are intentionally absent from every
    error, making this helper safe to reuse in the API and Streamlit UI.
    """

    inline = os.environ.get("TRANSCRIPTION_V2_API_TOKEN", "").strip()
    token_file_value = os.environ.get("TRANSCRIPTION_V2_API_TOKEN_FILE", "").strip()
    if inline and token_file_value:
        raise ValueError(
            "TRANSCRIPTION_V2_API_TOKEN and TRANSCRIPTION_V2_API_TOKEN_FILE are mutually exclusive"
        )
    if token_file_value:
        return _read_private_token_file(Path(token_file_value).expanduser())
    return _validate_api_token(inline)


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = int(raw)
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = float(raw)
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


@dataclass(frozen=True, slots=True)
class Settings:
    data_root: Path
    database_path: Path
    bind_host: str = "127.0.0.1"
    bind_port: int = 8510
    api_token: str = ""
    api_token_file: Path | None = None
    pipeline_backend: str = "mock"
    inference_device: str = "cuda"
    cpu_compute_type: str = "int8"
    worker_poll_seconds: float = 1.0
    worker_id: str = "worker-local"
    max_upload_bytes: int = 5 * 1024**3
    max_batch_upload_bytes: int = 5 * 1024**3
    upload_chunk_bytes: int = 1024**2
    max_files_per_request: int = 100
    max_retained_jobs_per_owner: int = 100
    max_retained_bytes_per_owner: int = 10 * 1024**3
    max_retained_jobs_global: int = 400
    max_retained_bytes_global: int = 40 * 1024**3
    minimum_free_disk_bytes: int = 100 * 1024**3
    delivery_token_seconds: int = 10 * 60
    public_delivery_prefix: str = "/v1/delivery"
    # Delivery grace period only; this service is not a transcript archive.
    default_retention_hours: int = 4
    max_retention_hours: int = 24
    max_active_job_hours: int = 48
    max_media_duration_seconds: int = 12 * 60 * 60
    stale_job_minutes: int = 30
    gpu_lock_path: Path = Path("/run/lock/recordbench-transcription-gpu.lock")
    minimum_free_vram_mb: int = 20_000
    model_cache_dir: Path = Path(
        "/var/lib/recordbench/model-cache/huggingface/hub"
    )
    model_manifest_path: Path | None = None
    allow_degraded_diarization: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        data_root = Path(
            os.environ.get("TRANSCRIPTION_V2_DATA_ROOT", str(PROJECT_ROOT / "data"))
        ).expanduser().resolve()
        database_path = Path(
            os.environ.get("TRANSCRIPTION_V2_DATABASE", str(data_root / "jobs.sqlite3"))
        ).expanduser().resolve()
        model_cache_dir = Path(
            os.environ.get(
                "TRANSCRIPTION_V2_MODEL_CACHE",
                "/var/lib/recordbench/model-cache/huggingface/hub",
            )
        ).expanduser()
        token_file_value = os.environ.get("TRANSCRIPTION_V2_API_TOKEN_FILE", "").strip()
        max_upload_bytes = _env_int(
            "TRANSCRIPTION_V2_MAX_UPLOAD_BYTES", 5 * 1024**3, minimum=1
        )
        max_files_per_request = _env_int(
            "TRANSCRIPTION_V2_MAX_FILES", 100, minimum=1
        )
        max_retained_jobs_per_owner = _env_int(
            "TRANSCRIPTION_V2_MAX_RETAINED_JOBS_PER_OWNER", 100, minimum=1
        )
        max_retained_bytes_per_owner = _env_int(
            "TRANSCRIPTION_V2_MAX_RETAINED_BYTES_PER_OWNER",
            10 * 1024**3,
            minimum=1,
        )
        # Older deployments do not define a batch limit. Derive a safe value
        # from their existing file and owner quotas so those environments keep
        # starting, while a clean configuration receives the new 5 GiB limit.
        compatible_batch_default = max(
            max_upload_bytes,
            min(
                5 * 1024**3,
                max_retained_bytes_per_owner,
                max_upload_bytes * max_files_per_request,
            ),
        )
        settings = cls(
            data_root=data_root,
            database_path=database_path,
            bind_host=os.environ.get("TRANSCRIPTION_V2_BIND_HOST", "127.0.0.1").strip(),
            bind_port=_env_int("TRANSCRIPTION_V2_BIND_PORT", 8510, minimum=1),
            api_token=load_api_token_from_env(),
            api_token_file=Path(token_file_value).expanduser() if token_file_value else None,
            pipeline_backend=os.environ.get("TRANSCRIPTION_V2_PIPELINE", "mock").strip().lower(),
            inference_device=os.environ.get("TRANSCRIPTION_V2_DEVICE", "cuda").strip().lower(),
            cpu_compute_type=os.environ.get("TRANSCRIPTION_V2_CPU_COMPUTE_TYPE", "int8").strip().lower(),
            worker_poll_seconds=_env_float("TRANSCRIPTION_V2_WORKER_POLL_SECONDS", 1.0, minimum=0.1),
            worker_id=os.environ.get("TRANSCRIPTION_V2_WORKER_ID", "worker-local").strip(),
            max_upload_bytes=max_upload_bytes,
            max_batch_upload_bytes=_env_int(
                "TRANSCRIPTION_V2_MAX_BATCH_UPLOAD_BYTES",
                compatible_batch_default,
                minimum=1,
            ),
            upload_chunk_bytes=_env_int("TRANSCRIPTION_V2_UPLOAD_CHUNK_BYTES", 1024**2, minimum=4096),
            max_files_per_request=max_files_per_request,
            max_retained_jobs_per_owner=max_retained_jobs_per_owner,
            max_retained_bytes_per_owner=max_retained_bytes_per_owner,
            max_retained_jobs_global=_env_int(
                "TRANSCRIPTION_V2_MAX_RETAINED_JOBS_GLOBAL", 400, minimum=1
            ),
            max_retained_bytes_global=_env_int(
                "TRANSCRIPTION_V2_MAX_RETAINED_BYTES_GLOBAL",
                40 * 1024**3,
                minimum=1,
            ),
            minimum_free_disk_bytes=_env_int(
                "TRANSCRIPTION_V2_MIN_FREE_DISK_BYTES",
                100 * 1024**3,
                minimum=0,
            ),
            delivery_token_seconds=_env_int(
                "TRANSCRIPTION_V2_DELIVERY_TOKEN_SECONDS", 10 * 60, minimum=30
            ),
            public_delivery_prefix=os.environ.get(
                "TRANSCRIPTION_V2_PUBLIC_DELIVERY_PREFIX", "/v1/delivery"
            ).strip().rstrip("/"),
            default_retention_hours=_env_int("TRANSCRIPTION_V2_RETENTION_HOURS", 4, minimum=1),
            max_retention_hours=_env_int("TRANSCRIPTION_V2_MAX_RETENTION_HOURS", 24, minimum=1),
            max_active_job_hours=_env_int(
                "TRANSCRIPTION_V2_MAX_ACTIVE_JOB_HOURS", 48, minimum=1
            ),
            max_media_duration_seconds=_env_int(
                "TRANSCRIPTION_V2_MAX_MEDIA_DURATION_SECONDS",
                12 * 60 * 60,
                minimum=1,
            ),
            stale_job_minutes=_env_int("TRANSCRIPTION_V2_STALE_JOB_MINUTES", 30, minimum=1),
            gpu_lock_path=Path(
                os.environ.get("TRANSCRIPTION_V2_GPU_LOCK_PATH", "/run/lock/recordbench-transcription-gpu.lock")
            ).expanduser(),
            minimum_free_vram_mb=_env_int("TRANSCRIPTION_V2_MIN_FREE_VRAM_MB", 20_000, minimum=0),
            model_cache_dir=model_cache_dir,
            model_manifest_path=Path(
                os.environ.get(
                    "TRANSCRIPTION_V2_MODEL_MANIFEST",
                    str(model_cache_dir / DEFAULT_MODEL_MANIFEST_NAME),
                )
            ).expanduser(),
            allow_degraded_diarization=_env_bool(
                "TRANSCRIPTION_V2_ALLOW_DEGRADED_DIARIZATION", False
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.bind_port > 65_535:
            raise ValueError("TRANSCRIPTION_V2_BIND_PORT must be at most 65535")
        if self.bind_host not in LOOPBACK_HOSTS and not self.api_token:
            raise ValueError(
                "TRANSCRIPTION_V2_API_TOKEN is required when binding the API beyond loopback"
            )
        _validate_api_token(self.api_token)
        if self.pipeline_backend not in {"mock", "whisperx"}:
            raise ValueError("TRANSCRIPTION_V2_PIPELINE must be 'mock' or 'whisperx'")
        if self.inference_device not in {"cpu", "cuda"}:
            raise ValueError("TRANSCRIPTION_V2_DEVICE must be 'cpu' or 'cuda'")
        if self.cpu_compute_type not in {"int8", "float32"}:
            raise ValueError("TRANSCRIPTION_V2_CPU_COMPUTE_TYPE must be 'int8' or 'float32'")
        if self.default_retention_hours > self.max_retention_hours:
            raise ValueError("default retention cannot exceed maximum retention")
        if self.max_active_job_hours > 7 * 24:
            raise ValueError("TRANSCRIPTION_V2_MAX_ACTIVE_JOB_HOURS must be at most 168")
        if self.max_media_duration_seconds > 7 * 24 * 60 * 60:
            raise ValueError(
                "TRANSCRIPTION_V2_MAX_MEDIA_DURATION_SECONDS must be at most 604800"
            )
        if self.max_files_per_request > 100:
            raise ValueError("TRANSCRIPTION_V2_MAX_FILES must be at most 100")
        if self.max_retained_jobs_per_owner < self.max_files_per_request:
            raise ValueError(
                "per-owner job quota cannot be smaller than one upload batch"
            )
        if self.max_batch_upload_bytes < self.max_upload_bytes:
            raise ValueError("batch byte limit cannot be smaller than one upload")
        if self.max_retained_bytes_per_owner < self.max_batch_upload_bytes:
            raise ValueError("per-owner byte quota cannot be smaller than one upload batch")
        if self.max_retained_jobs_global < self.max_retained_jobs_per_owner:
            raise ValueError("global job quota cannot be smaller than per-owner quota")
        if self.max_retained_bytes_global < self.max_retained_bytes_per_owner:
            raise ValueError("global byte quota cannot be smaller than per-owner quota")
        if self.delivery_token_seconds > 3600:
            raise ValueError("TRANSCRIPTION_V2_DELIVERY_TOKEN_SECONDS must be at most 3600")
        if (
            not self.public_delivery_prefix.startswith("/")
            or self.public_delivery_prefix.startswith("//")
            or ".." in self.public_delivery_prefix.split("/")
            or "?" in self.public_delivery_prefix
            or "#" in self.public_delivery_prefix
        ):
            raise ValueError("TRANSCRIPTION_V2_PUBLIC_DELIVERY_PREFIX must be a safe root-relative path")
        if not self.worker_id:
            raise ValueError("TRANSCRIPTION_V2_WORKER_ID must not be empty")
        try:
            self.approved_model_manifest_path.resolve(strict=False).relative_to(
                self.model_cache_dir.resolve(strict=False)
            )
        except ValueError as exc:
            raise ValueError(
                "TRANSCRIPTION_V2_MODEL_MANIFEST must stay inside TRANSCRIPTION_V2_MODEL_CACHE"
            ) from exc

    @property
    def approved_model_manifest_path(self) -> Path:
        """Return the explicit manifest or the cache-local safe default."""

        return self.model_manifest_path or self.model_cache_dir / DEFAULT_MODEL_MANIFEST_NAME

    def prepare_runtime(self) -> None:
        """Create only v2-owned runtime paths."""
        try:
            self.database_path.resolve().relative_to(self.data_root.resolve())
        except ValueError as exc:
            raise ValueError(
                "TRANSCRIPTION_V2_DATABASE must stay inside TRANSCRIPTION_V2_DATA_ROOT"
            ) from exc
        self.data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.data_root / "jobs").mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def public_dict(self) -> dict[str, object]:
        """Return operational settings with credentials intentionally omitted."""
        return {
            "bind_host": self.bind_host,
            "bind_port": self.bind_port,
            "pipeline_backend": self.pipeline_backend,
            "inference_device": self.inference_device,
            "cpu_compute_type": self.cpu_compute_type,
            "model_manifest_required": self.pipeline_backend == "whisperx",
            "allow_degraded_diarization": self.allow_degraded_diarization,
            "max_upload_bytes": self.max_upload_bytes,
            "max_batch_upload_bytes": self.max_batch_upload_bytes,
            "max_files_per_request": self.max_files_per_request,
            "max_retained_jobs_per_owner": self.max_retained_jobs_per_owner,
            "max_retained_bytes_per_owner": self.max_retained_bytes_per_owner,
            "max_retained_jobs_global": self.max_retained_jobs_global,
            "max_retained_bytes_global": self.max_retained_bytes_global,
            "minimum_free_disk_bytes": self.minimum_free_disk_bytes,
            "default_retention_hours": self.default_retention_hours,
            "max_retention_hours": self.max_retention_hours,
            "max_active_job_hours": self.max_active_job_hours,
            "max_media_duration_seconds": self.max_media_duration_seconds,
            "minimum_free_vram_mb": self.minimum_free_vram_mb,
        }
