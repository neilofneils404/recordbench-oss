#!/usr/bin/env python3
"""RecordBench node installer with an automation-safe retro terminal UI."""
from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import json
import os
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


PROJECT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0-alpha.2"
RELEASE_DIRECTORIES = (
    "benchmarks",
    "config",
    "deploy",
    "docs",
    "migrations",
    "schemas",
    "scripts",
    "services",
    "src",
)
RELEASE_FILES = (
    ".dockerignore",
    ".env.example",
    "AGENTS.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "Dockerfile",
    "LICENSE",
    "NOTICE",
    "README.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "compose.kerberos.yaml",
    "compose.local-accounts.yaml",
    "compose.yaml",
    "install",
    "pyproject.toml",
)


class C:
    green = "\033[38;5;46m"
    cyan = "\033[38;5;51m"
    magenta = "\033[38;5;201m"
    amber = "\033[38;5;220m"
    dim = "\033[2m"
    bold = "\033[1m"
    reset = "\033[0m"


@dataclass
class Console:
    color: bool
    quiet: bool = False

    def paint(self, value: str, color: str) -> str:
        return f"{color}{value}{C.reset}" if self.color else value

    def line(self, value: str = "") -> None:
        if not self.quiet:
            print(value, flush=True)

    def phase(self, number: int, title: str, detail: str) -> None:
        marker = self.paint(f"PHASE {number:02d}", C.magenta + C.bold)
        self.line(f"\n{marker}  {self.paint(title, C.cyan + C.bold)}")
        self.line(f"          {self.paint(detail, C.dim)}")

    def ok(self, value: str) -> None:
        self.line(f"  {self.paint('[OK]', C.green + C.bold)} {value}")

    def note(self, value: str) -> None:
        self.line(f"  {self.paint('[::]', C.cyan)} {value}")

    def warn(self, value: str) -> None:
        self.line(f"  {self.paint('[!!]', C.amber + C.bold)} {value}")

    def banner(self, mode: str) -> None:
        art = r"""
 ██████╗ ███████╗ ██████╗ ██████╗ ██████╗ ██████╗ ███████╗███╗   ██╗ ██████╗██╗  ██╗
 ██╔══██╗██╔════╝██╔════╝██╔═══██╗██╔══██╗██╔══██╗██╔════╝████╗  ██║██╔════╝██║  ██║
 ██████╔╝█████╗  ██║     ██║   ██║██████╔╝██║  ██║█████╗  ██╔██╗ ██║██║     ███████║
 ██╔══██╗██╔══╝  ██║     ██║   ██║██╔══██╗██║  ██║██╔══╝  ██║╚██╗██║██║     ██╔══██║
 ██║  ██║███████╗╚██████╗╚██████╔╝██║  ██║██████╔╝███████╗██║ ╚████║╚██████╗██║  ██║
 ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═══╝ ╚═════╝╚═╝  ╚═╝
""".strip("\n")
        self.line(self.paint(art, C.green + C.bold))
        self.line(
            self.paint(
                f"  EVIDENCE NODE PROVISIONER // {mode.upper()} // BUILD {VERSION}",
                C.cyan,
            )
        )
        self.line(self.paint("  LOCAL MODELS. PRIVATE RECORD. OPERATOR CONTROL.", C.dim))


@dataclass(frozen=True, slots=True)
class GpuDevice:
    index: str
    name: str
    total_mib: int
    free_mib: int
    compute_capability: float | None = None


@dataclass(frozen=True, slots=True)
class GpuPlan:
    layout: str
    generator_gpus: tuple[str, ...]
    transcription_gpu: str
    retrieval_device: str
    retrieval_gpu: str

    def environment(self) -> dict[str, str]:
        return {
            "RECORDBENCH_GPU_LAYOUT": self.layout,
            "RECORDBENCH_GENERATOR_GPU": ",".join(self.generator_gpus),
            "RECORDBENCH_GENERATOR_TENSOR_PARALLEL": str(
                max(len(self.generator_gpus), 1)
            ),
            "RECORDBENCH_TRANSCRIPTION_GPU": self.transcription_gpu,
            "RECORDBENCH_RETRIEVAL_DEVICE": self.retrieval_device,
            "RECORDBENCH_RETRIEVAL_GPU": self.retrieval_gpu,
        }


@dataclass(frozen=True, slots=True)
class ReviewModelPlan:
    profile: str
    model_id: str
    revision: str
    served_name: str
    dtype: str
    gpu_utilization: float
    max_sequences: int
    generation_concurrency: int
    transcription_min_free_vram_mib: int

    def environment(self) -> dict[str, str]:
        return {
            "RECORDBENCH_GENERATOR_MODEL_ID": self.model_id,
            "RECORDBENCH_GENERATOR_REVISION": self.revision,
            "RECORDBENCH_GENERATOR_SERVED_NAME": self.served_name,
            "RECORDBENCH_GENERATOR_DTYPE": self.dtype,
            "RECORDBENCH_GENERATOR_GPU_UTILIZATION": (
                f"{self.gpu_utilization:.2f}"
            ),
            "RECORDBENCH_GENERATOR_SEQUENCES": str(self.max_sequences),
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="./install",
        description="Provision or inspect a private RecordBench node.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("install", "doctor", "update", "backup", "restore"),
        default="install",
    )
    parser.add_argument("--root", type=Path, help="exact installation state directory")
    parser.add_argument("--storage-root", type=Path, help="dedicated local or mounted-NAS matter storage directory")
    parser.add_argument("--auth", choices=("local", "oidc", "kerberos"), default=None)
    parser.add_argument("--enable-account-management", action="store_true", help="enable browser account changes for an explicit --auth local installation")
    parser.add_argument("--models", choices=("none", "review", "transcription", "all"), default=None)
    parser.add_argument(
        "--gpu-layout",
        choices=("auto", "shared", "split"),
        default="auto",
        help="automatically pack or deliberately separate GPU workloads",
    )
    parser.add_argument(
        "--generator-gpus",
        help="comma-separated visible GPU indices for vLLM tensor parallelism",
    )
    parser.add_argument("--transcription-gpu", help="visible GPU index for WhisperX")
    parser.add_argument("--retrieval-gpu", help="visible GPU index for learned retrieval")
    parser.add_argument(
        "--retrieval-device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
    )
    parser.add_argument(
        "--review-model-profile",
        choices=("auto", "portable", "quality"),
        default="auto",
        help="choose a pinned generator tier or let preflight select by topology",
    )
    parser.add_argument("--generator-gpu-utilization", type=float)
    parser.add_argument("--transcription-min-free-vram-mib", type=int)
    parser.add_argument("--server-name")
    parser.add_argument("--bind-address")
    parser.add_argument("--https-port", type=int, default=8443)
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    parser.add_argument("--admin-username")
    parser.add_argument("--admin-display-name")
    parser.add_argument("--oidc-issuer")
    parser.add_argument("--oidc-client-id")
    parser.add_argument("--oidc-client-secret-file", type=Path)
    parser.add_argument("--oidc-allowed-groups")
    parser.add_argument("--oidc-admin-groups")
    parser.add_argument("--kerberos-realm")
    parser.add_argument("--kerberos-allowed-groups")
    parser.add_argument("--kerberos-admin-groups")
    parser.add_argument("--kerberos-keytab", type=Path)
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--password-stdin", action="store_true")
    parser.add_argument("--hf-token-stdin", action="store_true")
    parser.add_argument("--accept-model-terms", action="store_true")
    parser.add_argument(
        "--transcription-languages",
        default="en",
        help="comma-separated staged alignment languages: en and/or es",
    )
    parser.add_argument(
        "--enable-diarization",
        action="store_true",
        help="stage and enable the separately gated speaker-diarization module",
    )
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-backup", action="store_true", help="allow an update without a configured recovery snapshot")
    parser.add_argument("--repository", type=Path, help="encrypted restic repository for backup initialization")
    parser.add_argument("--recovery-key-output", type=Path, help="separate owner-only recovery credential path")
    parser.add_argument("--retention", default="14d")
    parser.add_argument("--allow-local-backup", action="store_true")
    parser.add_argument("--restore-target", type=Path)
    parser.add_argument("--snapshot", default="latest")
    parser.add_argument("--schedule-backups", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def _ask(prompt: str, default: str, *, non_interactive: bool) -> str:
    if non_interactive:
        return default
    value = input(f"{prompt} [{default}]: ").strip()
    return value or default


def _choose(prompt: str, choices: Sequence[str], default: str, *, non_interactive: bool) -> str:
    if non_interactive:
        return default
    rendered = "/".join(f"[{value}]" if value == default else value for value in choices)
    while True:
        value = input(f"{prompt} ({rendered}): ").strip().casefold() or default
        if value in choices:
            return value
        print(f"Choose one of: {', '.join(choices)}")


def _run(
    console: Console,
    command: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    input_value: str | None = None,
    check: bool = True,
    capture: bool = False,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    safe = " ".join(command)
    console.note(f"exec :: {safe}")
    if dry_run:
        return subprocess.CompletedProcess(command, 0, "", "")
    return subprocess.run(
        command,
        cwd=PROJECT,
        env=dict(env) if env is not None else None,
        input=input_value,
        text=True,
        check=check,
        capture_output=capture,
    )


def _require(command: str) -> str:
    value = shutil.which(command)
    if value is None:
        raise RuntimeError(f"required command is unavailable: {command}")
    return value


def _private_write(path: Path, value: str, *, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if replace else os.O_EXCL)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, value.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


def _private_copy(source: Path, target: Path) -> None:
    metadata = source.lstat()
    if source.is_symlink() or not source.is_file() or metadata.st_size > 1024 * 1024:
        raise RuntimeError("source credential file is unavailable or unsafe")
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        content = os.read(descriptor, 1024 * 1024 + 1)
    finally:
        os.close(descriptor)
    if not content or len(content) > 1024 * 1024:
        raise RuntimeError("source credential file is empty or too large")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(output, content)
        os.fsync(output)
    finally:
        os.close(output)


def _secret(path: Path, size: int = 48) -> str:
    if path.exists():
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not path.is_file()
            or (metadata.st_mode & 0o777) != 0o600
            or metadata.st_uid != os.geteuid()
            or not 16 <= metadata.st_size <= 16_384
        ):
            raise RuntimeError(f"existing secret file is unsafe: {path}")
        value = path.read_text(encoding="utf-8").strip()
        if not value or any(character in value for character in ("\x00", "\r", "\n")):
            raise RuntimeError(f"existing secret file is invalid: {path}")
        return value
    value = secrets.token_urlsafe(size)
    _private_write(path, value + "\n")
    return value


def _env_text(values: Mapping[str, object], heading: str) -> str:
    lines = [f"# {heading}", "# Generated by the RecordBench node provisioner."]
    for key, value in values.items():
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is None:
            raise RuntimeError("generated environment key is invalid")
        encoded = str(value)
        if any(character in encoded for character in ("\x00", "\r", "\n")):
            raise RuntimeError(f"generated environment value is invalid: {key}")
        lines.append(f"{key}={json.dumps(encoded)}")
    return "\n".join(lines) + "\n"


def _dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, encoded = line.partition("=")
        if (
            not separator
            or re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is None
            or key in values
        ):
            raise RuntimeError(f"invalid node environment line {number}")
        encoded = encoded.strip()
        if encoded.startswith('"'):
            try:
                value = json.loads(encoded)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid node environment line {number}") from exc
            if not isinstance(value, str):
                raise RuntimeError(f"invalid node environment line {number}")
        else:
            value = encoded
        if any(character in value for character in ("\x00", "\r", "\n")):
            raise RuntimeError(f"invalid node environment line {number}")
        values[key] = value
    return values


def _valid_host(value: str) -> str:
    candidate = value.strip().casefold()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", candidate):
        raise RuntimeError("server name is invalid")
    return candidate


def _release_sources() -> tuple[Path, ...]:
    sources: list[Path] = []
    for name in (*RELEASE_DIRECTORIES, *RELEASE_FILES):
        source = PROJECT / name
        if not source.exists() or source.is_symlink():
            raise RuntimeError(f"release source is missing or unsafe: {name}")
        sources.append(source)
    return tuple(sources)


def _release_digest() -> str:
    digest = hashlib.sha256()
    for source in _release_sources():
        paths = [source] if source.is_file() else sorted(source.rglob("*"))
        for path in paths:
            if path.is_symlink():
                raise RuntimeError(f"release source contains a symbolic link: {path}")
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            relative = path.relative_to(PROJECT).as_posix()
            digest.update(relative.encode("utf-8") + b"\0")
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            digest.update(b"\0")
    return digest.hexdigest()


def _copy_release_entry(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(
            source,
            destination,
            symlinks=False,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _stage_release(console: Console, root: Path, *, dry_run: bool) -> tuple[str, Path]:
    digest = _release_digest()
    release_id = f"{VERSION}-{digest[:12]}"
    destination = root / "releases" / release_id
    if dry_run:
        console.ok(f"release capsule :: {release_id}")
        return release_id, destination
    releases = root / "releases"
    releases.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(releases, 0o700)
    if destination.exists():
        manifest = destination / "RELEASE_MANIFEST.json"
        if destination.is_symlink() or not manifest.is_file():
            raise RuntimeError("existing release capsule is unsafe")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if payload.get("release_id") != release_id or payload.get("source_sha256") != digest:
            raise RuntimeError("existing release capsule failed integrity validation")
        console.ok(f"release capsule :: {release_id} (already staged)")
        return release_id, destination
    staging = Path(tempfile_name(releases, ".staging-release-"))
    staging.mkdir(mode=0o700)
    try:
        for source in _release_sources():
            _copy_release_entry(source, staging / source.name)
        manifest = {
            "format_version": 1,
            "version": VERSION,
            "release_id": release_id,
            "source_sha256": digest,
        }
        (staging / "RELEASE_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    console.ok(f"release capsule :: {release_id}")
    return release_id, destination


def tempfile_name(parent: Path, prefix: str) -> str:
    for _ in range(100):
        candidate = parent / f"{prefix}{secrets.token_hex(8)}"
        if not candidate.exists():
            return str(candidate)
    raise RuntimeError("could not allocate a release staging directory")


def _installed_release(root: Path) -> tuple[dict[str, object], Path]:
    path = root / "installation.json"
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("RecordBench node is not installed")
    try:
        installation = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("RecordBench installation record is invalid") from exc
    configured = installation.get("release_path")
    release = Path(configured) if isinstance(configured, str) else PROJECT
    if not release.is_absolute() or not (release / "compose.yaml").is_file():
        raise RuntimeError("installed release capsule is unavailable")
    return installation, release


def _compose(
    root: Path,
    profiles: Iterable[str],
    *,
    release: Path | None = None,
    auth: str | None = None,
    local_accounts: bool | None = None,
) -> list[str]:
    if local_accounts is None:
        try:
            record, _ = _installed_release(root)
            local_accounts = bool(record.get("local_account_management", False))
        except RuntimeError:
            local_accounts = False
    if release is None:
        try:
            installation, release = _installed_release(root)
            auth = auth or str(installation.get("auth", ""))
        except RuntimeError:
            release = PROJECT
    command = [
        "docker",
        "compose",
        "--env-file",
        str(root / "compose.env"),
        "-f",
        str(release / "compose.yaml"),
    ]
    if auth == "kerberos":
        command.extend(("-f", str(release / "compose.kerberos.yaml")))
    if local_accounts:
        command.extend(("-f", str(release / "compose.local-accounts.yaml")))
    for profile in profiles:
        command.extend(("--profile", profile))
    return command


def _required_gpu_count(models: str) -> int:
    if models == "none":
        return 0
    if models in {"review", "transcription"}:
        return 1
    if models == "all":
        return 1
    raise RuntimeError("model profile is invalid")


def _parse_gpu_inventory(value: str) -> tuple[GpuDevice, ...]:
    devices: list[GpuDevice] = []
    for row in csv.reader(value.splitlines()):
        if not row:
            continue
        if len(row) not in {4, 5}:
            raise RuntimeError("nvidia-smi returned an unexpected GPU inventory")
        try:
            compute_capability = (
                float(row[4].strip()) if len(row) == 5 else None
            )
            device = GpuDevice(
                index=row[0].strip(),
                name=row[1].strip(),
                total_mib=int(row[2].strip()),
                free_mib=int(row[3].strip()),
                compute_capability=compute_capability,
            )
        except ValueError as exc:
            raise RuntimeError("nvidia-smi returned an invalid GPU inventory") from exc
        if (
            not device.index
            or device.total_mib <= 0
            or device.free_mib < 0
            or (
                device.compute_capability is not None
                and device.compute_capability <= 0
            )
        ):
            raise RuntimeError("nvidia-smi returned an invalid GPU inventory")
        devices.append(device)
    if len({device.index for device in devices}) != len(devices):
        raise RuntimeError("nvidia-smi returned duplicate GPU indices")
    return tuple(devices)


def _gpu_selection(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    selected = tuple(item.strip() for item in value.split(",") if item.strip())
    if not selected or len(set(selected)) != len(selected):
        raise RuntimeError("GPU selection contains an empty or duplicate index")
    return selected


def _gpu_plan(
    models: str,
    devices: tuple[GpuDevice, ...],
    *,
    layout: str = "auto",
    generator_gpus: str | None = None,
    transcription_gpu: str | None = None,
    retrieval_device: str = "auto",
    retrieval_gpu: str | None = None,
) -> GpuPlan:
    required = _required_gpu_count(models)
    if layout not in {"auto", "shared", "split"}:
        raise RuntimeError("GPU layout is invalid")
    if retrieval_device not in {"auto", "cpu", "cuda"}:
        raise RuntimeError("retrieval device is invalid")
    eligible_devices = tuple(
        device
        for device in devices
        if device.compute_capability is None or device.compute_capability >= 7.5
    )
    if required and len(eligible_devices) < required:
        raise RuntimeError(
            f"the {models} profile requires at least {required} visible NVIDIA "
            "GPU(s) with compute capability 7.5 or newer"
        )
    ranked_devices = tuple(
        sorted(
            eligible_devices,
            key=lambda device: (
                -device.free_mib,
                -device.total_mib,
                (
                    (0, int(device.index))
                    if device.index.isdigit()
                    else (1, device.index)
                ),
            ),
        )
    )
    indices = tuple(device.index for device in ranked_devices)
    available = set(indices)
    if not indices:
        indices = ("0",)
    selected_generator = _gpu_selection(generator_gpus)
    if not selected_generator:
        selected_generator = (indices[0],)
    generator_set = set(selected_generator)
    if transcription_gpu:
        selected_transcription = transcription_gpu
    elif models == "all" and layout != "shared":
        selected_transcription = next(
            (index for index in indices if index not in generator_set),
            selected_generator[0],
        )
    elif models == "all":
        selected_transcription = selected_generator[0]
    else:
        selected_transcription = indices[0]

    if (
        layout == "split"
        and models == "all"
        and selected_transcription in generator_set
    ):
        raise RuntimeError(
            "the split full profile requires distinct generator and transcription GPUs"
        )
    if (
        layout == "shared"
        and models == "all"
        and selected_transcription not in generator_set
    ):
        raise RuntimeError(
            "the shared full profile requires transcription on a generator GPU"
        )

    selected_retrieval_device = retrieval_device
    occupied = set(selected_generator) if models in {"review", "all"} else set()
    if models in {"transcription", "all"}:
        occupied.add(selected_transcription)
    remaining = tuple(index for index in indices if index not in occupied)
    if selected_retrieval_device == "auto":
        selected_retrieval_device = (
            "cuda"
            if retrieval_gpu
            or (models in {"review", "all"} and remaining and layout != "shared")
            else "cpu"
        )
    if retrieval_gpu and selected_retrieval_device == "cpu":
        raise RuntimeError("--retrieval-gpu requires --retrieval-device cuda or auto")
    if retrieval_gpu:
        selected_retrieval = retrieval_gpu
    elif selected_retrieval_device == "cuda":
        selected_retrieval = remaining[0] if remaining else selected_generator[0]
    else:
        selected_retrieval = indices[0]

    if (
        layout == "split"
        and selected_retrieval_device == "cuda"
        and selected_retrieval in occupied
    ):
        raise RuntimeError(
            "the split profile requires a distinct retrieval GPU or CPU retrieval"
        )

    used = {*selected_generator}
    if models in {"transcription", "all"}:
        used.add(selected_transcription)
    if models in {"review", "all"} and selected_retrieval_device == "cuda":
        used.add(selected_retrieval)
    if devices and not used.issubset(available):
        missing = ",".join(sorted(used - available))
        raise RuntimeError(f"GPU selection is not visible to nvidia-smi: {missing}")

    effective_layout = layout
    if layout == "auto":
        separated_transcription = bool(
            models == "all" and selected_transcription not in generator_set
        )
        separated_retrieval = bool(
            models in {"review", "all"}
            and selected_retrieval_device == "cuda"
            and selected_retrieval not in generator_set
        )
        effective_layout = (
            "split" if separated_transcription or separated_retrieval else "shared"
        )
    return GpuPlan(
        layout=effective_layout,
        generator_gpus=selected_generator,
        transcription_gpu=selected_transcription,
        retrieval_device=selected_retrieval_device,
        retrieval_gpu=selected_retrieval,
    )


def _review_model_plan(
    models: str,
    devices: tuple[GpuDevice, ...],
    gpu_plan: GpuPlan,
    *,
    requested_profile: str = "auto",
    gpu_utilization: float | None = None,
    transcription_min_free_vram_mib: int | None = None,
) -> ReviewModelPlan:
    if requested_profile not in {"auto", "portable", "quality"}:
        raise RuntimeError("review model profile is invalid")
    device_map = {device.index: device for device in devices}
    generator_devices = [
        device_map[index]
        for index in gpu_plan.generator_gpus
        if index in device_map
    ]
    minimum_total_mib = min(
        (device.total_mib for device in generator_devices), default=0
    )
    tensor_parallel_size = max(len(generator_devices), 1)
    shared_with_transcription = bool(
        models == "all"
        and gpu_plan.transcription_gpu in set(gpu_plan.generator_gpus)
    )
    profile = requested_profile
    if profile == "auto":
        profile = "quality" if minimum_total_mib >= 40_000 else "portable"

    definitions = {
        "portable": (
            "Qwen/Qwen3.5-4B",
            "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
            "recordbench-qwen35-4b",
        ),
        "quality": (
            "Qwen/Qwen3.5-9B",
            "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            "recordbench-qwen35-9b",
        ),
    }
    model_id, revision, served_name = definitions[profile]
    if models in {"review", "all"} and devices:
        if profile == "portable":
            if tensor_parallel_size == 1:
                threshold = 20_000 if shared_with_transcription else 16_000
            else:
                threshold = 16_000 if shared_with_transcription else 12_000
        elif tensor_parallel_size == 1:
            threshold = 40_000 if shared_with_transcription else 32_000
        elif tensor_parallel_size == 2:
            threshold = 28_000 if shared_with_transcription else 20_000
        else:
            threshold = 24_000 if shared_with_transcription else 16_000
        if minimum_total_mib < threshold:
            raise RuntimeError(
                f"the {profile} review profile needs at least {threshold} MiB "
                "on each selected generator GPU for this topology"
            )

    utilization = gpu_utilization
    if utilization is None:
        if profile == "portable":
            utilization = 0.50 if shared_with_transcription else 0.60
        else:
            utilization = 0.50 if shared_with_transcription else 0.72
    if not 0.20 <= utilization <= 0.95:
        raise RuntimeError("generator GPU utilization must be between 0.20 and 0.95")
    minimum_free = transcription_min_free_vram_mib
    if minimum_free is None:
        minimum_free = 7_000 if shared_with_transcription else 12_000
    if minimum_free < 1_000:
        raise RuntimeError("transcription minimum free VRAM must be at least 1000 MiB")
    if models in {"review", "all"}:
        for device in generator_devices:
            required_free = int(device.total_mib * utilization) + 1_024
            if device.free_mib < required_free:
                raise RuntimeError(
                    f"generator GPU {device.index} currently has "
                    f"{device.free_mib} MiB free; this plan reserves "
                    f"approximately {required_free} MiB. Stop competing "
                    "workloads or select another device."
                )
    if models in {"transcription", "all"} and devices:
        transcription_device = device_map.get(gpu_plan.transcription_gpu)
        if transcription_device is not None:
            required_free = minimum_free + 1_024
            if gpu_plan.transcription_gpu in set(gpu_plan.generator_gpus):
                required_free += int(
                    transcription_device.total_mib * utilization
                )
            if transcription_device.free_mib < required_free:
                raise RuntimeError(
                    f"transcription GPU {transcription_device.index} currently "
                    f"has {transcription_device.free_mib} MiB free; this plan "
                    f"needs approximately {required_free} MiB before startup. "
                    "Stop competing workloads or select another device."
                )
    max_sequences = (
        4 if profile == "portable" or shared_with_transcription else 8
    )
    generation_concurrency = (
        2 if profile == "portable" or shared_with_transcription else 4
    )
    dtype = (
        "bfloat16"
        if generator_devices
        and all(
            device.compute_capability is not None
            and device.compute_capability >= 8.0
            for device in generator_devices
        )
        else "half"
    )
    return ReviewModelPlan(
        profile=profile,
        model_id=model_id,
        revision=revision,
        served_name=served_name,
        dtype=dtype,
        gpu_utilization=utilization,
        max_sequences=max_sequences,
        generation_concurrency=generation_concurrency,
        transcription_min_free_vram_mib=minimum_free,
    )


def _resolve_gpu_plans(
    args: argparse.Namespace,
    models: str,
    devices: tuple[GpuDevice, ...],
) -> tuple[GpuPlan, ReviewModelPlan]:
    explicit_topology = bool(
        args.gpu_layout != "auto"
        or args.generator_gpus
        or args.transcription_gpu
        or args.retrieval_gpu
        or args.retrieval_device != "auto"
    )
    layouts = [args.gpu_layout]
    if not explicit_topology and models == "all" and len(devices) > 1:
        layouts.append("shared")
    if args.review_model_profile == "auto" and models in {"review", "all"}:
        profiles = ("quality", "portable")
    else:
        profiles = (
            "portable"
            if args.review_model_profile == "auto"
            else args.review_model_profile,
        )
    failures: list[str] = []
    for profile in profiles:
        for layout in dict.fromkeys(layouts):
            try:
                gpu_plan = _gpu_plan(
                    models,
                    devices,
                    layout=layout,
                    generator_gpus=args.generator_gpus,
                    transcription_gpu=args.transcription_gpu,
                    retrieval_device=args.retrieval_device,
                    retrieval_gpu=args.retrieval_gpu,
                )
                review_model = _review_model_plan(
                    models,
                    devices,
                    gpu_plan,
                    requested_profile=profile,
                    gpu_utilization=args.generator_gpu_utilization,
                    transcription_min_free_vram_mib=(
                        args.transcription_min_free_vram_mib
                    ),
                )
                return gpu_plan, review_model
            except RuntimeError as exc:
                failures.append(str(exc))
                if explicit_topology and args.review_model_profile != "auto":
                    raise
    detail = failures[-1] if failures else "no compatible GPU lane was found"
    raise RuntimeError(f"automatic GPU planning failed: {detail}")


def _transcription_languages(value: str) -> tuple[str, ...]:
    languages = tuple(
        sorted({item.strip().casefold() for item in value.split(",") if item.strip()})
    )
    if not languages or not set(languages).issubset({"en", "es"}):
        raise RuntimeError("transcription languages must select en and/or es")
    return languages


def _model_stage_groups(
    models: str,
    *,
    transcription_languages: tuple[str, ...],
    diarization: bool,
) -> tuple[str, ...]:
    _required_gpu_count(models)
    groups: list[str] = []
    if models in {"review", "all"}:
        groups.append("review")
    if models in {"transcription", "all"}:
        groups.append("transcription-asr")
        groups.extend(
            f"transcription-alignment-{language}"
            for language in transcription_languages
        )
        if diarization:
            groups.append("transcription-diarization")
    elif diarization:
        raise RuntimeError("diarization requires a transcription capability profile")
    return tuple(groups)


def _preflight(
    console: Console, *, models: str, dry_run: bool
) -> tuple[GpuDevice, ...]:
    console.phase(1, "HOST HANDSHAKE", "Interrogating kernel, container runtime, disk, and accelerators")
    if os.geteuid() == 0 and not dry_run:
        raise RuntimeError(
            "run the installer as a dedicated non-root service account; "
            "pre-create and assign its node and storage directories first"
        )
    _require("docker")
    _require("openssl")
    _run(console, ["docker", "info", "--format", "{{.ServerVersion}}"], capture=True, dry_run=dry_run)
    _run(console, ["docker", "compose", "version"], capture=True, dry_run=dry_run)
    console.ok("Docker engine and Compose plugin answered the challenge")
    required_gpus = _required_gpu_count(models)
    devices: tuple[GpuDevice, ...] = ()
    if required_gpus:
        _require("nvidia-smi")
        result = _run(
            console,
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free,compute_cap",
                "--format=csv,noheader,nounits",
            ],
            capture=True,
            # GPU discovery is read-only and remains authoritative during a
            # dry run; fabricating a card would produce an unsafe plan.
            dry_run=False,
        )
        if result.stdout:
            devices = _parse_gpu_inventory(result.stdout)
            if not dry_run and any(
                device.compute_capability is None for device in devices
            ):
                raise RuntimeError(
                    "nvidia-smi did not report GPU compute capability; "
                    "the CUDA compatibility check cannot complete safely"
                )
            for device in devices:
                console.ok(
                    f"GPU lane :: {device.index}, {device.name}, "
                    f"{device.total_mib} MiB total, {device.free_mib} MiB free, "
                    f"compute {device.compute_capability or 'unknown'}"
                )
        if len(devices) < required_gpus:
            raise RuntimeError(
                f"the {models} profile requires at least {required_gpus} "
                f"visible NVIDIA GPU(s); detected {len(devices)}"
            )
    return devices


def _paths(root: Path, storage_root: Path | None = None) -> dict[str, Path]:
    return {
        "config": root / "config",
        "secrets": root / "secrets",
        "accounts": root / "accounts",
        "runtime": root / "runtime",
        "storage": storage_root or root / "matter-storage",
        "transcription": root / "transcription",
        "state": root / "state",
        "models": root / "models",
        "tls": root / "tls",
    }


def _prepare_directories(
    console: Console,
    root: Path,
    *,
    storage_root: Path | None,
    resume: bool,
    dry_run: bool,
) -> dict[str, Path]:
    console.phase(2, "CLAIM NODE STORAGE", "Creating narrow, owner-controlled state boundaries")
    if not root.is_absolute() or root == Path("/"):
        raise RuntimeError("--root must be an exact absolute directory other than /")
    if root.is_symlink():
        raise RuntimeError("installation root cannot be a symbolic link")
    if root.exists() and any(root.iterdir()) and not resume:
        raise RuntimeError("installation root is not empty; use --resume only for this RecordBench node")
    selected_storage = storage_root.expanduser().resolve(strict=False) if storage_root else None
    if selected_storage is not None and (
        not selected_storage.is_absolute() or selected_storage == Path("/")
    ):
        raise RuntimeError("--storage-root must be an exact absolute directory other than /")
    if selected_storage is not None and selected_storage.exists() and selected_storage.is_symlink():
        raise RuntimeError("matter storage root cannot be a symbolic link")
    paths = _paths(root, selected_storage)
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        for value in paths.values():
            value.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(value, 0o700)
    for name, value in paths.items():
        console.ok(f"{name:13s} -> {value}")
    return paths


def _password(args: argparse.Namespace) -> str:
    if args.password_stdin:
        value = sys.stdin.readline(4097).rstrip("\r\n")
    elif args.non_interactive:
        raise RuntimeError("local non-interactive installation requires --password-stdin")
    else:
        value = getpass.getpass("Initial administrator password: ")
        if value != getpass.getpass("Confirm administrator password: "):
            raise RuntimeError("administrator passwords did not match")
    if not 14 <= len(value) <= 1024:
        raise RuntimeError("administrator password must contain 14 to 1,024 characters")
    return value


def _hf_token(args: argparse.Namespace) -> str:
    if args.hf_token_stdin:
        value = sys.stdin.readline(4097).rstrip("\r\n")
    elif args.non_interactive:
        raise RuntimeError("transcription staging requires --hf-token-stdin")
    else:
        value = getpass.getpass("Read-only Hugging Face token (used once, never retained): ")
    if not value or len(value) > 4096:
        raise RuntimeError("Hugging Face token is missing or invalid")
    return value


def _configure(
    console: Console,
    args: argparse.Namespace,
    root: Path,
    paths: Mapping[str, Path],
    release_id: str,
    release_path: Path,
    gpu_devices: tuple[GpuDevice, ...],
) -> tuple[str, str, str, str | None, str | None]:
    console.phase(4, "IDENTITY + FRONT DOOR", "Sealing sessions, service credentials, and HTTPS coordinates")
    auth = args.auth or _choose(
        "Identity mode", ("local", "oidc", "kerberos"), "local", non_interactive=args.non_interactive
    )
    models = args.models or "none"
    transcription_languages = _transcription_languages(
        args.transcription_languages
    )
    _model_stage_groups(
        models,
        transcription_languages=transcription_languages,
        diarization=bool(args.enable_diarization),
    )
    gpu_plan, review_model = _resolve_gpu_plans(args, models, gpu_devices)
    args.review_model_profile = review_model.profile
    server_name = _valid_host(
        args.server_name
        or _ask("RecordBench hostname", "recordbench.example.test", non_interactive=args.non_interactive)
    )
    bind = args.bind_address or _ask(
        "HTTPS bind address", "127.0.0.1", non_interactive=args.non_interactive
    )
    if not 1 <= args.https_port <= 65535:
        raise RuntimeError("HTTPS port is invalid")
    profile_values = []
    if models in {"all", "review"}:
        profile_values.append("ai")
    if models in {"all", "transcription"}:
        profile_values.append("transcription")

    postgres_password = "dry-run-secret" if args.dry_run else _secret(paths["secrets"] / "postgres-password")
    if not args.dry_run:
        _secret(paths["secrets"] / "transcription-token")
        dsn = f"host=postgres port=5432 dbname=recordbench user=recordbench password={postgres_password}\n"
        dsn_path = paths["secrets"] / "postgres-dsn"
        if not dsn_path.exists():
            _private_write(dsn_path, dsn)

    tls_cert = args.tls_cert
    tls_key = args.tls_key
    if bool(tls_cert) != bool(tls_key):
        raise RuntimeError("--tls-cert and --tls-key must be supplied together")
    if tls_cert is None:
        if bind not in {"127.0.0.1", "::1"}:
            raise RuntimeError("a LAN bind requires an organization-trusted --tls-cert and --tls-key")
        tls_cert, tls_key = paths["tls"] / "tls.crt", paths["tls"] / "tls.key"
        if not tls_cert.exists() and not args.dry_run:
            _run(
                console,
                [
                    "openssl", "req", "-x509", "-newkey", "rsa:3072", "-sha256", "-nodes",
                    "-days", "825", "-subj", f"/CN={server_name}",
                    "-addext", f"subjectAltName=DNS:{server_name},IP:127.0.0.1",
                    "-keyout", str(tls_key), "-out", str(tls_cert),
                ],
            )
            os.chmod(tls_key, 0o600)
        console.warn("Generated a loopback smoke certificate; replace it before staff access")
    for value in (tls_cert, tls_key):
        if not args.dry_run and (value is None or not value.is_file() or value.is_symlink()):
            raise RuntimeError("TLS material is unavailable or unsafe")

    compose_values = {
        "RECORDBENCH_COMPOSE_PROJECT": f"recordbench-{hashlib_short(root)}",
        "RECORDBENCH_IMAGE_NAMESPACE": f"recordbench-{hashlib_short(root)}",
        "RECORDBENCH_RELEASE_ID": release_id,
        "RECORDBENCH_UID": os.getuid(),
        "RECORDBENCH_GID": os.getgid(),
        "RECORDBENCH_CONFIG_ROOT": paths["config"],
        "RECORDBENCH_SECRETS_ROOT": paths["secrets"],
        "RECORDBENCH_RUNTIME_ROOT": paths["runtime"],
        "RECORDBENCH_STORAGE_ROOT": paths["storage"],
        "RECORDBENCH_TRANSCRIPTION_ROOT": paths["transcription"],
        "RECORDBENCH_STATE_ROOT": paths["state"],
        "RECORDBENCH_MODEL_ROOT": paths["models"],
        "RECORDBENCH_BIND_ADDRESS": bind,
        "RECORDBENCH_HTTPS_PORT": args.https_port,
        "RECORDBENCH_SERVER_NAME": server_name,
        "RECORDBENCH_TLS_CERT": tls_cert,
        "RECORDBENCH_TLS_KEY": tls_key,
        "RECORDBENCH_GATEWAY_UPSTREAM": "app:8786",
        "COMPOSE_PROFILES": ",".join(profile_values),
        **gpu_plan.environment(),
        **review_model.environment(),
    }
    app_values: dict[str, object] = {
        "CASE_INTELLIGENCE_AUTH_MODE": auth,
        "CASE_INTELLIGENCE_SECURE_COOKIE": 1,
        "CASE_INTELLIGENCE_GENERATOR_BACKEND": "openai" if models in {"all", "review"} else "",
        "CASE_INTELLIGENCE_GENERATOR_URL": "http://generator:8000",
        "CASE_INTELLIGENCE_GENERATOR_MODEL": review_model.served_name,
        "CASE_INTELLIGENCE_GENERATOR_DISABLE_THINKING": 1,
        "CASE_INTELLIGENCE_GENERATOR_TIMEOUT": 180,
        "CASE_INTELLIGENCE_GENERATION_CONCURRENCY": (
            review_model.generation_concurrency
        ),
        "CASE_INTELLIGENCE_TRANSCRIPTION_URL": "http://transcription-api:8510" if models in {"all", "transcription"} else "",
        "CASE_INTELLIGENCE_BACKGROUND_INGESTION": 1,
        "CASE_INTELLIGENCE_INGESTION_WORKERS": 2,
        "CASE_INTELLIGENCE_ANSWER_WORKERS": 2,
        "CASE_INTELLIGENCE_RESEARCH_WORKERS": 1,
        "CASE_INTELLIGENCE_FULL_REVIEW_WORKERS": 1,
        "CASE_INTELLIGENCE_FULL_REVIEW_SOURCE_CONCURRENCY": 2,
        "CASE_INTELLIGENCE_OCR_MODE": "expanded",
        "CASE_INTELLIGENCE_OCR_LANGUAGE": "eng",
        "CASE_INTELLIGENCE_MAX_OCR_PAGES": 500,
        "CASE_INTELLIGENCE_MALWARE_SCAN_MODE": "extended",
        "CASE_INTELLIGENCE_MAINTENANCE_ENABLED": 1,
        "CASE_INTELLIGENCE_MAINTENANCE_INTERVAL_SECONDS": 900,
        "CASE_INTELLIGENCE_MATTER_QUOTA_GIB": 250,
        "CASE_INTELLIGENCE_UPLOAD_COLLECTION_GIB": 100,
        "CASE_INTELLIGENCE_MEDIA_FILE_GIB": 100,
        "CASE_INTELLIGENCE_DOCUMENT_FILE_MIB": 512,
        "CASE_INTELLIGENCE_STORAGE_RESERVE_GIB": 100,
    }
    admin_username = admin_display = None
    if auth == "local":
        if args.enable_account_management:
            compose_values["RECORDBENCH_LOCAL_ACCOUNT_ROOT"] = paths["accounts"]
            app_values["CASE_INTELLIGENCE_LOCAL_ACCOUNTS_FILE"] = "/var/lib/recordbench-accounts/local-accounts.json"
            app_values["CASE_INTELLIGENCE_LOCAL_ACCOUNT_MANAGEMENT_ROOT"] = "/var/lib/recordbench-accounts"
        else:
            app_values["CASE_INTELLIGENCE_LOCAL_ACCOUNTS_FILE"] = "/run/recordbench-secrets/local-accounts.json"
        admin_username = args.admin_username or _ask(
            "Initial administrator username", "recordbench.admin", non_interactive=args.non_interactive
        )
        admin_display = args.admin_display_name or _ask(
            "Administrator display name", "RecordBench Administrator", non_interactive=args.non_interactive
        )
    elif auth == "oidc":
        issuer = args.oidc_issuer or _ask(
            "OIDC issuer URL",
            "https://identity.example.test/realms/case-team",
            non_interactive=args.non_interactive,
        )
        client_id = args.oidc_client_id or _ask(
            "OIDC client ID", "recordbench", non_interactive=args.non_interactive
        )
        allowed_groups = args.oidc_allowed_groups or _ask(
            "OIDC allowed groups",
            "RecordBench_Users",
            non_interactive=args.non_interactive,
        )
        administrator_groups = args.oidc_admin_groups or _ask(
            "OIDC administrator groups",
            "RecordBench_Administrators",
            non_interactive=args.non_interactive,
        )
        app_values.update(
            {
                "CASE_INTELLIGENCE_EXTERNAL_ORIGIN": f"https://{server_name}" + (f":{args.https_port}" if args.https_port != 443 else ""),
                "CASE_INTELLIGENCE_OIDC_ISSUER": issuer,
                "CASE_INTELLIGENCE_OIDC_CLIENT_ID": client_id,
                "CASE_INTELLIGENCE_OIDC_CLIENT_SECRET_FILE": "/run/recordbench-secrets/oidc-client-secret",
                "CASE_INTELLIGENCE_OIDC_ALLOWED_GROUPS": allowed_groups,
                "CASE_INTELLIGENCE_OIDC_ADMIN_GROUPS": administrator_groups,
                "CASE_INTELLIGENCE_OIDC_SCOPES": "openid profile email",
            }
        )
        if not args.dry_run and not (paths["secrets"] / "oidc-client-secret").exists():
            if args.oidc_client_secret_file is not None:
                _private_copy(
                    args.oidc_client_secret_file.expanduser(),
                    paths["secrets"] / "oidc-client-secret",
                )
            elif args.non_interactive:
                raise RuntimeError(
                    "non-interactive OIDC installation requires "
                    "--oidc-client-secret-file"
                )
            else:
                _private_write(
                    paths["secrets"] / "oidc-client-secret",
                    getpass.getpass("OIDC client secret: ") + "\n",
                )
    else:
        realm = (
            args.kerberos_realm
            or _ask(
                "Kerberos realm",
                "EXAMPLE.TEST",
                non_interactive=args.non_interactive,
            )
        ).upper()
        compose_values["RECORDBENCH_KERBEROS_PRINCIPAL"] = f"HTTP/{server_name}@{realm}"
        app_values.update(
            {
                "CASE_INTELLIGENCE_KERBEROS_REALM": realm,
                "CASE_INTELLIGENCE_KERBEROS_ALLOWED_GROUPS": args.kerberos_allowed_groups
                or _ask(
                    "Allowed Kerberos group",
                    "recordbench_users@example.test",
                    non_interactive=args.non_interactive,
                ),
                "CASE_INTELLIGENCE_KERBEROS_ADMIN_GROUPS": args.kerberos_admin_groups
                or _ask(
                    "Administrator Kerberos group",
                    "recordbench_administrators@example.test",
                    non_interactive=args.non_interactive,
                ),
                "CASE_INTELLIGENCE_KERBEROS_PROXY_SECRET_FILE": "/run/recordbench-secrets/kerberos-proxy-secret",
            }
        )
        if not args.dry_run:
            _secret(paths["secrets"] / "kerberos-proxy-secret")
            target_keytab = paths["secrets"] / "recordbench.keytab"
            if not target_keytab.exists():
                source_keytab = args.kerberos_keytab
                if source_keytab is None and not args.non_interactive:
                    source_keytab = Path(input("Path to the exported HTTP service keytab: ").strip())
                if source_keytab is None:
                    raise RuntimeError("Kerberos installation requires --kerberos-keytab")
                _private_copy(source_keytab.expanduser(), target_keytab)
            if not Path("/var/lib/sss/pipes").is_dir() or not Path("/etc/krb5.conf").is_file():
                raise RuntimeError("Kerberos mode requires a working host SSSD/NSS join and /etc/krb5.conf")
        console.ok("Kerberos keytab and host NSS bridge selected")

    transcription_values = {
        "TRANSCRIPTION_V2_PIPELINE": "mock",
        "TRANSCRIPTION_V2_WORKER_ID": "recordbench-transcription-worker-1",
        "TRANSCRIPTION_V2_WORKER_POLL_SECONDS": 1,
        "TRANSCRIPTION_V2_LANGUAGE_CODES": (
            "auto," + ",".join(transcription_languages)
        ),
        "TRANSCRIPTION_V2_MODEL_MANIFEST": "/models/huggingface/hub/approved-model-manifest.json",
        "TRANSCRIPTION_V2_DIARIZATION_MODEL_PATH": (
            "/models/huggingface/hub/models--pyannote--speaker-diarization-community-1/"
            "snapshots/3533c8cf8e369892e6b79ff1bf80f7b0286a54ee/config.yaml"
            if args.enable_diarization
            else ""
        ),
        "TRANSCRIPTION_V2_ALLOW_DEGRADED_DIARIZATION": (
            0 if args.enable_diarization else 1
        ),
        "TRANSCRIPTION_V2_MIN_FREE_VRAM_MB": (
            review_model.transcription_min_free_vram_mib
        ),
        "TRANSCRIPTION_V2_GPU_LOCK_PATH": "/tmp/recordbench-transcription-gpu.lock",
        "TRANSCRIPTION_V2_RETENTION_HOURS": 24,
        "TRANSCRIPTION_V2_MAX_RETENTION_HOURS": 24,
        "TRANSCRIPTION_V2_MAX_ACTIVE_JOB_HOURS": 48,
        "TRANSCRIPTION_V2_MAX_UPLOAD_BYTES": 5368709120,
        "TRANSCRIPTION_V2_MAX_BATCH_UPLOAD_BYTES": 21474836480,
        "TRANSCRIPTION_V2_MAX_FILES": 100,
        "TRANSCRIPTION_V2_MAX_RETAINED_JOBS_PER_OWNER": 100,
        "TRANSCRIPTION_V2_MAX_RETAINED_BYTES_PER_OWNER": 214748364800,
        "TRANSCRIPTION_V2_MAX_RETAINED_JOBS_GLOBAL": 400,
        "TRANSCRIPTION_V2_MAX_RETAINED_BYTES_GLOBAL": 858993459200,
        "TRANSCRIPTION_V2_MIN_FREE_DISK_BYTES": 107374182400,
        "TRANSCRIPTION_V2_MAX_MEDIA_DURATION_SECONDS": 43200,
        "TRANSCRIPTION_V2_DELIVERY_TOKEN_SECONDS": 600,
        "HF_HUB_OFFLINE": 1,
        "TRANSFORMERS_OFFLINE": 1,
        "HF_DATASETS_OFFLINE": 1,
        "PYANNOTE_METRICS_ENABLED": 0,
    }
    if not args.dry_run:
        _private_write(root / "compose.env", _env_text(compose_values, "RecordBench Compose node"), replace=(root / "compose.env").exists())
        _private_write(paths["config"] / "recordbench.env", _env_text(app_values, "RecordBench application"), replace=(paths["config"] / "recordbench.env").exists())
        _private_write(paths["config"] / "transcription.env", _env_text(transcription_values, "RecordBench transcription"), replace=(paths["config"] / "transcription.env").exists())
        _private_write(
            root / "installation.json",
            json.dumps(
                {
                    "format_version": 1,
                    "version": VERSION,
                    "release_id": release_id,
                    "release_path": str(release_path),
                    "node_id": hashlib_short(root),
                    "storage_root": str(paths["storage"]),
                    "auth": auth,
                    "local_account_management": bool(args.enable_account_management),
                    "models": models,
                    "transcription_languages": list(transcription_languages),
                    "transcription_diarization": bool(args.enable_diarization),
                    "gpu_layout": gpu_plan.layout,
                    "gpu_topology": {
                        "visible_devices": len(gpu_devices),
                        "generator": list(gpu_plan.generator_gpus),
                        "transcription": gpu_plan.transcription_gpu,
                        "retrieval_device": gpu_plan.retrieval_device,
                        "retrieval_gpu": (
                            gpu_plan.retrieval_gpu
                            if gpu_plan.retrieval_device == "cuda"
                            else None
                        ),
                    },
                    "review_model_profile": review_model.profile,
                    "server_name": server_name,
                    "profiles": profile_values,
                },
                indent=2,
            )
            + "\n",
            replace=(root / "installation.json").exists(),
        )
    console.ok(f"identity matrix :: {auth}")
    console.ok(f"model payload   :: {models}")
    console.ok(
        "GPU topology    :: "
        f"{gpu_plan.layout}; generator={','.join(gpu_plan.generator_gpus)}; "
        f"transcription={gpu_plan.transcription_gpu}; "
        f"retrieval={gpu_plan.retrieval_device}"
        + (
            f":{gpu_plan.retrieval_gpu}"
            if gpu_plan.retrieval_device == "cuda"
            else ""
        )
        + f"; visible={len(gpu_devices)}"
    )
    assigned = set(gpu_plan.generator_gpus)
    if models in {"transcription", "all"}:
        assigned.add(gpu_plan.transcription_gpu)
    if models in {"review", "all"} and gpu_plan.retrieval_device == "cuda":
        assigned.add(gpu_plan.retrieval_gpu)
    if len(gpu_devices) > len(assigned):
        console.note(
            f"GPU reserve     :: {len(gpu_devices) - len(assigned)} visible "
            "device(s) intentionally unassigned"
        )
    if models in {"review", "all"}:
        console.ok(
            f"review model    :: {review_model.profile} ({review_model.model_id})"
        )
    console.ok(f"front door      :: https://{server_name}:{args.https_port}")
    return auth, models, server_name, admin_username, admin_display


def hashlib_short(path: Path) -> str:
    import hashlib

    return hashlib.sha256(str(path).encode()).hexdigest()[:10]


def _replace_env(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    encoded = json.dumps(value)
    output = []
    changed = False
    for line in lines:
        if line.startswith(key + "="):
            output.append(f"{key}={encoded}")
            changed = True
        else:
            output.append(line)
    if not changed:
        output.append(f"{key}={encoded}")
    _private_write(path, "\n".join(output) + "\n", replace=True)


def _atomic_private_write(path: Path, value: str) -> None:
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}-{secrets.token_hex(4)}")
    _private_write(temporary, value)
    os.replace(temporary, path)


def _provision_marker(root: Path) -> Path:
    return root / "state" / "provisioned.json"


def _provisioning_complete(root: Path, installation: Mapping[str, object]) -> bool:
    marker = _provision_marker(root)
    if marker.is_symlink() or not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        payload.get("release_id") == installation.get("release_id")
        and payload.get("auth") == installation.get("auth")
        and payload.get("models") == installation.get("models")
    )


def _seal_provisioning(root: Path, installation: Mapping[str, object]) -> None:
    payload = {
        "format_version": 1,
        "release_id": installation.get("release_id"),
        "auth": installation.get("auth"),
        "models": installation.get("models"),
        "completed_unix": int(time.time()),
    }
    _atomic_private_write(
        _provision_marker(root), json.dumps(payload, indent=2) + "\n"
    )


def _provision(
    console: Console,
    args: argparse.Namespace,
    root: Path,
    auth: str,
    models: str,
    admin_username: str | None,
    admin_display: str | None,
) -> None:
    profiles = ["tools"]
    if models in {"all", "review"}:
        profiles.append("ai")
    if models in {"all", "transcription"}:
        profiles.append("transcription")
    compose = _compose(root, profiles, auth=auth, local_accounts=args.enable_account_management)

    console.phase(5, "FORGE RUNTIME", "Building isolated OCR, review, retrieval, and transcription images")
    targets = ["app", "account-admin"]
    if auth == "kerberos":
        targets.append("kerberos-proxy")
    if models in {"all", "review"}:
        targets.extend(("retrieval",))
    if models in {"all", "transcription"}:
        targets.extend(("transcription-api", "transcription-worker"))
    _run(console, [*compose, "build", *targets], dry_run=args.dry_run)
    console.ok("Runtime images forged")

    console.phase(6, "SEAL CONTROL PLANE", "Initializing managed storage and attributed access")
    if args.dry_run:
        storage_root = args.storage_root or root / "matter-storage"
    else:
        installation, _release = _installed_release(root)
        configured_storage = installation.get("storage_root")
        if not isinstance(configured_storage, str):
            raise RuntimeError("installed matter storage path is invalid")
        storage_root = Path(configured_storage)
    marker = storage_root / ".recordbench-managed-storage.json"
    if not marker.exists():
        _run(
            console,
            [*compose, "run", "--rm", "--no-deps", "account-admin", "storage", "init", "--root", "/var/lib/recordbench/matter-storage"],
            dry_run=args.dry_run,
        )
    account_directory = root / ("accounts" if args.enable_account_management else "secrets")
    account_container_file = "/var/lib/recordbench-accounts/local-accounts.json" if args.enable_account_management else "/run/recordbench-secrets/local-accounts.json"
    if auth == "local" and not (account_directory / "local-accounts.json").exists():
        if not admin_username or not admin_display:
            raise RuntimeError(
                "unfinished local installation requires --admin-username and "
                "--admin-display-name when resumed"
            )
        password = "dry-run-password-placeholder" if args.dry_run else _password(args)
        try:
            _run(
                console,
                [*compose, "run", "--rm", "--no-deps", "-T", "account-admin", "accounts", "init", "--file", account_container_file, "--username", str(admin_username), "--display-name", str(admin_display), "--password-stdin"],
                input_value=password + "\n",
                dry_run=args.dry_run,
            )
        finally:
            password = ""
    console.ok("Managed storage boundary and identity control plane sealed")

    if models != "none":
        console.phase(7, "OPEN MODEL VAULT", "Acquiring exact revisions, hashing artifacts, then cutting network access")
        languages = _transcription_languages(args.transcription_languages)
        groups = ",".join(
            _model_stage_groups(
                models,
                transcription_languages=languages,
                diarization=bool(args.enable_diarization),
            )
        )
        token = None
        if models in {"all", "transcription"} and args.enable_diarization:
            if not args.accept_model_terms:
                if args.non_interactive:
                    raise RuntimeError("transcription staging requires --accept-model-terms")
                console.warn("Community-1 is gated and CC-BY-4.0; accept its upstream terms before continuing")
                if input("Type ACCEPT after reviewing the linked model terms: ").strip() != "ACCEPT":
                    raise RuntimeError("model terms were not accepted")
            token = _hf_token(args)
        command = [
            *compose,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "model-stager",
            "stage",
            "--groups",
            groups,
            "--review-profile",
            args.review_model_profile,
        ]
        if token is not None:
            command.append("--token-stdin")
        try:
            _run(console, command, input_value=(token + "\n") if token else None, dry_run=args.dry_run)
        finally:
            token = None
        if models in {"all", "transcription"} and not args.dry_run:
            _replace_env(root / "config" / "transcription.env", "TRANSCRIPTION_V2_PIPELINE", "whisperx")
        console.ok("Model vault sealed; runtime services retain no hub token")

    if not args.dry_run:
        installation, _release = _installed_release(root)
        _seal_provisioning(root, installation)

    if args.prepare_only:
        console.phase(8, "NODE ARMED", "Preparation complete; services intentionally remain stopped")
        console.ok(f"Resume with: ./install install --root {root} --resume")
        return
    console.phase(8, "IGNITE NODE", "Launching the private service mesh and waiting for health consensus")
    active = []
    if models in {"all", "review"}:
        active.append("ai")
    if models in {"all", "transcription"}:
        active.append("transcription")
    runtime_compose = _compose(root, active, local_accounts=args.enable_account_management)
    _run(console, [*runtime_compose, "up", "-d", "--remove-orphans"], dry_run=args.dry_run)
    if not args.dry_run:
        _wait_health(console, root)
    console.ok("RecordBench node is online")


def _selected_capabilities_ready(payload: Mapping[str, object], models: str) -> bool:
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict):
        return False
    if models in {"review", "all"} and not (
        capabilities.get("answering") == "ready"
        and capabilities.get("search") == "word + meaning"
    ):
        return False
    if models in {"transcription", "all"} and not str(
        capabilities.get("transcription", "")
    ).startswith("local WhisperX"):
        return False
    return True


def _wait_health(console: Console, root: Path) -> None:
    settings = json.loads((root / "installation.json").read_text(encoding="utf-8"))
    env = _dotenv(root / "compose.env")
    host = settings["server_name"]
    port = int(env.get("RECORDBENCH_HTTPS_PORT", "8443"))
    url = f"https://127.0.0.1:{port}/health"
    context = ssl._create_unverified_context()
    deadline = time.monotonic() + 900
    next_report = time.monotonic() + 15
    last = None
    if settings.get("auth") == "kerberos":
        compose = _compose(root, settings.get("profiles", []))
        models = str(settings.get("models", "none"))
        probe = (
            "import json,urllib.request; "
            "p=json.load(urllib.request.urlopen('http://127.0.0.1:8786/health',timeout=5)); "
            "assert p.get('status') in {'ok','degraded'} and p.get('product')=='RecordBench' "
            "and p.get('storage',{}).get('status')=='ready'; "
            f"c=p.get('capabilities',{{}}); m={models!r}; "
            "assert m not in {'review','all'} or "
            "(c.get('answering')=='ready' and c.get('search')=='word + meaning'); "
            "assert m not in {'transcription','all'} or "
            "str(c.get('transcription','')).startswith('local WhisperX')"
        )
        _run(console, [*compose, "exec", "-T", "app", "python", "-c", probe])
        console.ok("Application health passed behind the Kerberos boundary")
        try:
            request = urllib.request.Request(url, headers={"Host": host})
            urllib.request.urlopen(request, timeout=5, context=context)
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and "Negotiate" in exc.headers.get("WWW-Authenticate", ""):
                console.ok("HTTPS front door issued the expected Negotiate challenge")
                return
            raise RuntimeError("Kerberos gateway did not issue a valid challenge") from exc
        raise RuntimeError("Kerberos gateway did not protect the unauthenticated health route")
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(url, headers={"Host": host})
            with urllib.request.urlopen(request, timeout=5, context=context) as response:
                payload = json.load(response)
            storage = payload.get("storage")
            if (
                payload.get("status") in {"ok", "degraded"}
                and payload.get("product") == "RecordBench"
                and isinstance(storage, dict)
                and storage.get("status") == "ready"
                and _selected_capabilities_ready(
                    payload, str(settings.get("models", "none"))
                )
            ):
                console.ok("HTTPS gateway and application health contract passed")
                if payload.get("status") == "degraded":
                    console.warn(
                        "Node is useful but an unselected optional capability is unavailable"
                    )
                return
            last = "health or selected capability contract was not ready"
        except Exception as exc:
            last = exc.__class__.__name__
        if time.monotonic() >= next_report:
            console.note(f"health consensus pending :: {last or 'services are starting'}")
            next_report = time.monotonic() + 15
        time.sleep(3)
    raise RuntimeError(f"node did not reach health before timeout ({last})")


def _doctor(console: Console, args: argparse.Namespace, root: Path) -> None:
    console.phase(1, "NODE DIAGNOSTIC", "Checking configuration, permissions, Compose graph, and live health")
    required = (root / "compose.env", root / "installation.json", root / "config" / "recordbench.env")
    for path in required:
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"required node file is unavailable: {path}")
        console.ok(f"control file :: {path.name}")
    config = json.loads((root / "installation.json").read_text(encoding="utf-8"))
    profiles = list(config.get("profiles", []))
    compose = _compose(root, profiles)
    _run(console, [*compose, "config", "--quiet"], dry_run=args.dry_run)
    _run(console, [*compose, "ps"], dry_run=args.dry_run)
    if not args.dry_run:
        _wait_health(console, root)
    console.ok("Node diagnostic complete")


def _resume_node(console: Console, args: argparse.Namespace, root: Path) -> None:
    installation, _release = _installed_release(root)
    auth = str(installation.get("auth", ""))
    models = str(installation.get("models", "none"))
    installed_languages = installation.get("transcription_languages", ["en"])
    if not isinstance(installed_languages, list) or not all(
        isinstance(value, str) for value in installed_languages
    ):
        raise RuntimeError("installed transcription language metadata is invalid")
    args.transcription_languages = ",".join(installed_languages)
    args.enable_diarization = bool(
        installation.get("transcription_diarization", False)
    )
    args.review_model_profile = str(
        installation.get("review_model_profile", "portable")
    )
    profiles = installation.get("profiles", [])
    if (
        auth not in {"local", "oidc", "kerberos"}
        or models not in {"none", "review", "transcription", "all"}
        or not isinstance(profiles, list)
    ):
        raise RuntimeError("installed node metadata is invalid")
    _preflight(console, models=models, dry_run=args.dry_run)
    console.phase(2, "REJOIN NODE", "Using sealed identity, storage, model, and release coordinates")
    compose = _compose(root, profiles)
    _run(console, [*compose, "config", "--quiet"], dry_run=args.dry_run)
    console.ok(f"release capsule :: {installation.get('release_id', 'legacy')}")
    if not _provisioning_complete(root, installation):
        console.warn("Prior boot stopped before the provisioning seal; safely replaying idempotent phases")
        _provision(
            console,
            args,
            root,
            auth,
            models,
            args.admin_username,
            args.admin_display_name,
        )
        return
    console.phase(3, "IGNITE NODE", "Launching the prepared service mesh and waiting for health consensus")
    _run(console, [*compose, "up", "-d", "--remove-orphans"], dry_run=args.dry_run)
    if not args.dry_run:
        _wait_health(console, root)
    console.ok("Prepared RecordBench node is online")


def _backup_tool(root: Path) -> Path:
    _installation, release = _installed_release(root)
    tool = release / "scripts" / "recordbench_backup.py"
    if tool.is_symlink() or not tool.is_file():
        raise RuntimeError("installed release does not contain the backup tool")
    return tool


def _systemd_quote(value: str) -> str:
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise RuntimeError("systemd unit path is invalid")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _schedule_backup(console: Console, root: Path, *, dry_run: bool) -> None:
    installation, release = _installed_release(root)
    node_id = str(installation.get("node_id", ""))
    if re.fullmatch(r"[0-9a-f]{10}", node_id) is None:
        raise RuntimeError("node identity is invalid")
    user_units = Path.home() / ".config" / "systemd" / "user"
    service_name = f"recordbench-backup-{node_id}.service"
    timer_name = f"recordbench-backup-{node_id}.timer"
    replacements = {
        "@NODE_ID@": node_id,
        "@RELEASE_ROOT@": str(release),
        "@PYTHON@": _systemd_quote(sys.executable),
        "@TOOL@": _systemd_quote(str(_backup_tool(root))),
        "@NODE_ROOT@": _systemd_quote(str(root)),
    }
    if not dry_run:
        user_units.mkdir(parents=True, exist_ok=True)
        for template_name, destination_name in (
            ("recordbench-backup.service.in", service_name),
            ("recordbench-backup.timer.in", timer_name),
        ):
            text = (release / "deploy" / "systemd" / template_name).read_text(
                encoding="utf-8"
            )
            for marker, value in replacements.items():
                text = text.replace(marker, value)
            if "@" in text:
                raise RuntimeError("backup timer template contains an unresolved marker")
            destination = user_units / destination_name
            temporary = destination.with_name(destination.name + ".tmp")
            temporary.write_text(text, encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        _run(console, ["systemctl", "--user", "daemon-reload"])
        _run(console, ["systemctl", "--user", "enable", "--now", timer_name])
        _atomic_private_write(
            root / "state" / "backup-unit.json",
            json.dumps(
                {
                    "format_version": 1,
                    "service": service_name,
                    "timer": timer_name,
                    "release_path": str(release),
                },
                indent=2,
            )
            + "\n",
        )
    console.ok(f"quiet-hour timer :: {timer_name}")


def _backup(console: Console, args: argparse.Namespace, root: Path) -> None:
    console.phase(1, "FREEZE THE RECORD", "Checking queues, snapshot boundaries, and encrypted recovery storage")
    tool = _backup_tool(root)
    config = root / "config" / "backup.json"
    if args.repository is not None or args.recovery_key_output is not None:
        if args.repository is None or args.recovery_key_output is None:
            raise RuntimeError("backup initialization needs both --repository and --recovery-key-output")
        command = [
            sys.executable,
            str(tool),
            "initialize",
            "--node-root",
            str(root),
            "--repository",
            str(args.repository.expanduser().resolve(strict=False)),
            "--recovery-key-output",
            str(args.recovery_key_output.expanduser().resolve(strict=False)),
            "--retention",
            args.retention,
        ]
        if args.allow_local_backup:
            command.append("--allow-local-repository")
        _run(console, command, dry_run=args.dry_run)
    elif not config.is_file():
        raise RuntimeError(
            "backup is not initialized; provide --repository and --recovery-key-output"
        )
    console.phase(2, "TRANSMIT VAULT SNAPSHOT", "Quiescing briefly, restarting service, then transferring encrypted blocks")
    command = [sys.executable, str(tool), "backup", "--node-root", str(root)]
    if args.dry_run:
        command.append("--dry-run")
    _run(console, command, dry_run=args.dry_run)
    console.ok("Backup sequence completed or safely deferred by active work")
    if args.schedule_backups:
        console.phase(3, "ARM QUIET-HOUR DAEMON", "Scheduling the daily snapshot and one automatic retry")
        _schedule_backup(console, root, dry_run=args.dry_run)


def _restore(console: Console, args: argparse.Namespace, root: Path) -> None:
    if args.restore_target is None:
        raise RuntimeError("restore requires --restore-target with a new exact directory")
    console.phase(1, "RECOVERY SIMULATION", "Restoring encrypted evidence into an isolated, never-live target")
    tool = _backup_tool(root)
    _run(
        console,
        [
            sys.executable,
            str(tool),
            "restore",
            "--node-root",
            str(root),
            "--target",
            str(args.restore_target.expanduser().resolve(strict=False)),
            "--snapshot",
            args.snapshot,
        ],
        dry_run=args.dry_run,
    )
    console.ok("Restore drill cryptographic and database checks passed")


def _build_targets(auth: str, models: str) -> list[str]:
    targets = ["app", "account-admin"]
    if auth == "kerberos":
        targets.append("kerberos-proxy")
    if models in {"all", "review"}:
        targets.append("retrieval")
    if models in {"all", "transcription"}:
        targets.extend(("transcription-api", "transcription-worker"))
    return targets


def _update(console: Console, args: argparse.Namespace, root: Path) -> None:
    installation, old_release = _installed_release(root)
    auth = str(installation.get("auth", ""))
    models = str(installation.get("models", "none"))
    profiles = installation.get("profiles", [])
    if auth not in {"local", "oidc", "kerberos"} or models not in {
        "none",
        "review",
        "transcription",
        "all",
    } or not isinstance(profiles, list):
        raise RuntimeError("installed node metadata is invalid")
    _preflight(console, models=models, dry_run=args.dry_run)
    console.phase(2, "SNAPSHOT BEFORE MUTATION", "Requiring a recoverable checkpoint before swapping release capsules")
    backup_configured = (root / "config" / "backup.json").is_file()
    if backup_configured:
        _run(
            console,
            [sys.executable, str(_backup_tool(root)), "backup", "--node-root", str(root)],
            dry_run=args.dry_run,
        )
        console.ok("Pre-update encrypted snapshot completed or safely deferred")
        status_path = root / "state" / "backup-status.json"
        if not args.dry_run:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status.get("state") != "succeeded":
                raise RuntimeError("update requires a newly succeeded backup, not a deferred snapshot")
    elif not args.no_backup:
        raise RuntimeError(
            "backup is not configured; initialize it first or explicitly accept risk with --no-backup"
        )
    else:
        console.warn("Operator explicitly accepted an update without a recovery snapshot")

    console.phase(3, "LOAD NEW RELEASE CAPSULE", "Hashing an allowlisted source tree and preserving the prior runtime intact")
    release_id, release = _stage_release(console, root, dry_run=args.dry_run)
    if release_id == installation.get("release_id"):
        console.ok("Node already runs this exact release capsule")
        if not args.dry_run:
            _doctor(console, args, root)
        return
    old_installation_text = (root / "installation.json").read_text(encoding="utf-8")
    old_compose_text = (root / "compose.env").read_text(encoding="utf-8")
    updated = dict(installation)
    updated.update(
        {
            "version": VERSION,
            "release_id": release_id,
            "release_path": str(release),
            "previous_release_id": installation.get("release_id", ""),
            "previous_release_path": str(old_release),
        }
    )
    if not args.dry_run:
        _replace_env(root / "compose.env", "RECORDBENCH_RELEASE_ID", release_id)
        _atomic_private_write(
            root / "installation.json", json.dumps(updated, indent=2) + "\n"
        )
    compose = _compose(root, profiles, release=release, auth=auth)
    console.phase(4, "FORGE REPLACEMENT RUNTIME", "Building versioned images without overwriting the rollback image set")
    try:
        _run(console, [*compose, "build", *_build_targets(auth, models)], dry_run=args.dry_run)
        console.phase(5, "ATOMIC NODE SWAP", "Starting the new capsule and waiting for application and storage consensus")
        _run(console, [*compose, "up", "-d", "--remove-orphans"], dry_run=args.dry_run)
        if not args.dry_run:
            _wait_health(console, root)
            _seal_provisioning(root, updated)
            if (root / "state" / "backup-unit.json").is_file():
                _schedule_backup(console, root, dry_run=False)
        console.ok(f"Update committed :: {release_id}")
    except Exception as update_error:
        console.warn("New capsule failed acceptance; rolling back configuration and versioned images")
        rollback_error: Exception | None = None
        if not args.dry_run:
            try:
                _atomic_private_write(root / "compose.env", old_compose_text)
                _atomic_private_write(root / "installation.json", old_installation_text)
                rollback = _compose(root, profiles, release=old_release, auth=auth)
                _run(console, [*rollback, "up", "-d", "--remove-orphans"])
                _wait_health(console, root)
                console.ok("Prior release restored and healthy")
            except Exception as exc:
                rollback_error = exc
                console.warn("Prior capsule did not recover; operator intervention is required")
        if rollback_error is not None:
            raise RuntimeError(
                f"update failed ({update_error}); rollback also failed ({rollback_error})"
            ) from update_error
        raise RuntimeError(f"update failed and rollback was attempted: {update_error}") from update_error


def main() -> int:
    args = _parser().parse_args()
    if args.enable_account_management and (args.command != "install" or args.auth != "local"):
        _parser().error("--enable-account-management requires a new install with explicit --auth local; use the account relocation playbook for an existing node")
    console = Console(
        color=sys.stdout.isatty() and not args.no_color and os.getenv("NO_COLOR") is None,
        quiet=args.quiet,
    )
    console.banner(args.command)
    try:
        if args.root is None:
            default_root = Path("/srv/recordbench")
            args.root = Path(
                _ask(
                    "Installation state root",
                    str(default_root),
                    non_interactive=args.non_interactive,
                )
            )
        root = args.root.expanduser().resolve(strict=False)
        if args.command == "doctor":
            _doctor(console, args, root)
            return 0
        if args.command == "backup":
            _backup(console, args, root)
            console.line(console.paint("  >>> VAULT SNAPSHOT COMPLETE <<<", C.green + C.bold))
            return 0
        if args.command == "restore":
            _restore(console, args, root)
            console.line(console.paint("  >>> RECOVERY DRILL VERIFIED <<<", C.green + C.bold))
            return 0
        if args.command == "update":
            _update(console, args, root)
            console.line(console.paint("  >>> NODE UPGRADE COMPLETE <<<", C.green + C.bold))
            return 0
        if args.resume and (root / "installation.json").is_file():
            _resume_node(console, args, root)
            console.line(console.paint("  >>> ACCESS GRANTED // RECORD BENCH READY <<<", C.green + C.bold))
            console.line(console.paint(f"  node state :: {root}", C.dim))
            return 0
        if args.models is None:
            args.models = _choose(
                "Capability profile",
                ("none", "review", "transcription", "all"),
                "none",
                non_interactive=args.non_interactive,
            )
        models = args.models
        gpu_devices = _preflight(console, models=models, dry_run=args.dry_run)
        # Resolve the complete hardware plan before creating node directories or
        # staging a release. Unsupported or currently oversubscribed devices
        # leave no partial installation state behind.
        _resolve_gpu_plans(args, models, gpu_devices)
        if args.storage_root is None and not args.non_interactive:
            args.storage_root = Path(
                _ask(
                    "Managed matter storage root",
                    str(root / "matter-storage"),
                    non_interactive=False,
                )
            )
        paths = _prepare_directories(
            console,
            root,
            storage_root=args.storage_root,
            resume=args.resume,
            dry_run=args.dry_run,
        )
        console.phase(3, "LOAD RELEASE CAPSULE", "Hashing and staging only the deployable open-source tree")
        release_id, release_path = _stage_release(console, root, dry_run=args.dry_run)
        auth, models, _server_name, admin_user, admin_display = _configure(
            console, args, root, paths, release_id, release_path, gpu_devices
        )
        _provision(console, args, root, auth, models, admin_user, admin_display)
        console.line()
        console.line(console.paint("  >>> ACCESS GRANTED // RECORD BENCH READY <<<", C.green + C.bold))
        console.line(console.paint(f"  node state :: {root}", C.dim))
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        console.line()
        console.warn(f"BOOT SEQUENCE HALTED :: {exc}")
        console.line("  No secret values were written to terminal output.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
