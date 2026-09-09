#!/usr/bin/env python3
"""RecordBench node installer with an automation-safe retro terminal UI."""
from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import ipaddress
import json
import os
import platform
import re
import secrets
import shutil
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, replace
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
        choices=("install", "preflight", "doctor", "update", "backup", "restore"),
        default="install",
    )
    parser.add_argument("--root", type=Path, help="exact installation state directory")
    parser.add_argument("--storage-root", type=Path, help="dedicated local or mounted-NAS matter storage directory")
    parser.add_argument("--auth", choices=("local", "oidc", "kerberos"), default=None)
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
    parser.add_argument("--json", action="store_true", help="emit a structured preflight result (preflight command only)")
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


IDENTITY_FIELDS = {
    "local": (
        ("admin_username", "Initial administrator username", "recordbench.admin"),
        ("admin_display_name", "Administrator display name", "RecordBench Administrator"),
    ),
    "oidc": (
        ("oidc_issuer", "OIDC issuer URL", "https://identity.example.test/realms/case-team"),
        ("oidc_client_id", "OIDC client ID", "recordbench"),
        ("oidc_allowed_groups", "OIDC allowed groups", "RecordBench_Users"),
        ("oidc_admin_groups", "OIDC administrator groups", "RecordBench_Administrators"),
    ),
    "kerberos": (
        ("kerberos_realm", "Kerberos realm", "EXAMPLE.TEST"),
        ("kerberos_allowed_groups", "Allowed Kerberos group", "recordbench_users@example.test"),
        ("kerberos_admin_groups", "Administrator Kerberos group", "recordbench_administrators@example.test"),
    ),
}


def _collect_identity_choices(args: argparse.Namespace) -> None:
    """Collect non-secret choices once so preflight checks the actual installation."""
    if args.auth is None:
        args.auth = _choose("Identity mode", ("local", "oidc", "kerberos"), "local",
                            non_interactive=args.non_interactive)
    for name, prompt, default in IDENTITY_FIELDS[args.auth]:
        if getattr(args, name) is None:
            setattr(args, name, _ask(prompt, default, non_interactive=args.non_interactive))
    if args.auth == "local":
        args.admin_username = args.admin_username.strip().casefold()
        args.admin_display_name = args.admin_display_name.strip()
    if args.auth == "kerberos":
        args.kerberos_realm = args.kerberos_realm.upper()
        if args.kerberos_keytab is None and not args.non_interactive and not args.dry_run:
            args.kerberos_keytab = Path(_ask("Path to the exported HTTP service keytab", "", non_interactive=False))


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


def _credential_source_available(source: Path | None, *, maximum_bytes: int = 1024 * 1024) -> bool:
    """Check credential-file metadata without opening or retaining its contents."""
    if source is None:
        return False
    try:
        source = source.expanduser()
        metadata = source.lstat()
        return (stat.S_ISREG(metadata.st_mode) and 0 < metadata.st_size <= maximum_bytes
                and os.access(source, os.R_OK))
    except OSError:
        return False


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
    except (OSError, ValueError) as exc:
        raise RuntimeError("RecordBench installation record is invalid") from exc
    if (not isinstance(installation, dict)
            or installation.get("auth") not in ("local", "oidc", "kerberos")
            or installation.get("models", "none") not in ("none", "review", "transcription", "all")
            or not isinstance(installation.get("profiles", []), list)
            or not all(isinstance(profile, str) for profile in installation.get("profiles", []))):
        raise RuntimeError("RecordBench installation record is invalid")
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
) -> list[str]:
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
    requested_dtype: str | None = None,
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
    if requested_dtype is not None and models in {"review", "all"}:
        if requested_dtype not in {"half", "bfloat16"}:
            raise RuntimeError("saved generator dtype must be half or bfloat16")
        if requested_dtype == "bfloat16" and dtype != "bfloat16":
            raise RuntimeError(
                "saved bfloat16 generator dtype requires compute capability "
                "8.0 or newer on every selected generator GPU; restore compatible "
                "hardware or explicitly reconfigure the saved runtime precision"
            )
        dtype = requested_dtype
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
                    requested_dtype=getattr(args, "generator_dtype", None),
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


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    state: str
    observed: str
    required_capability: str
    blocking: bool
    remedy: str


@dataclass(frozen=True)
class PreflightResult:
    checks: tuple[PreflightCheck, ...]
    devices: tuple[GpuDevice, ...] = ()

    @property
    def ready(self) -> bool:
        return not any(check.blocking and check.state != "pass" for check in self.checks)

    def payload(self) -> dict[str, object]:
        return {"schema_version": 1, "ready": self.ready,
                "checks": [asdict(check) for check in self.checks]}


def _probe(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    # Diagnostic commands never print arbitrary runtime output (which may contain
    # operator topology) and cannot hang an unattended first-run check forever.
    return subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)


def _storage_ancestors_safe(ancestor: Path) -> bool:
    """Require a private creation point and a non-replaceable parent chain."""
    uid = os.geteuid()
    # The portable no-follow descriptor walk opens directories read-only, so
    # check its read/search requirements before reporting a usable path.
    if not os.access(ancestor, os.R_OK | os.X_OK):
        return False
    creation = ancestor.stat()
    if not stat.S_ISDIR(creation.st_mode) or creation.st_uid != uid or creation.st_mode & 0o022:
        return False
    for parent in ancestor.parents:
        if not os.access(parent, os.R_OK | os.X_OK):
            return False
        metadata = parent.stat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid not in {0, uid}:
            return False
        # A trusted sticky system directory protects each owned child from
        # replacement, e.g. an existing private test directory beneath /tmp.
        # It is never itself accepted as the writable creation point above.
        if metadata.st_mode & 0o022 and not metadata.st_mode & stat.S_ISVTX:
            return False
    return True


def _identity_options_valid(args: argparse.Namespace) -> bool:
    """Mirror non-secret identity.py settings without importing runtime dependencies."""
    values = {name: getattr(args, name) if getattr(args, name) is not None else default
              for name, _prompt, default in IDENTITY_FIELDS[args.auth]}
    if any(any(character in value for character in ("\x00", "\r", "\n"))
           for value in values.values()):
        return False
    groups = []
    for suffix, limit in (("allowed_groups", 100), ("admin_groups", 50)):
        selected = {value.strip() for value in values[f"{args.auth}_{suffix}"].split(",") if value.strip()}
        if args.auth == "kerberos":
            selected = {value.casefold() for value in selected}
            valid = all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@\\ -]{0,254}", value) for value in selected)
        else:
            valid = all(len(value) <= 256 and not any(ord(character) < 32 for character in value)
                        for value in selected)
        if len(selected) > limit or not valid:
            return False
        groups.append(selected)
    if args.auth == "kerberos":
        realm = values["kerberos_realm"].strip().upper()
        return bool(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", realm)
                    and "." in realm and any(groups))
    client = values["oidc_client_id"].strip()
    if not client or len(client) > 512 or any(ord(character) < 32 for character in client):
        return False
    for value, origin_only in ((values["oidc_issuer"], False),
                               (f"https://{(args.server_name or 'recordbench.example.test').strip().casefold()}:{args.https_port}", True)):
        candidate = value.strip().rstrip("/")
        if not candidate or len(candidate) > 1024:
            return False
        try:
            parsed = urllib.parse.urlsplit(candidate)
            if (parsed.scheme != "https" or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.query or parsed.fragment
                    or (origin_only and parsed.path not in {"", "/"})):
                return False
            hostname = parsed.hostname.casefold()
            if hostname == "localhost":
                return False
            try:
                if ipaddress.ip_address(hostname).is_loopback:
                    return False
            except ValueError:
                pass
        except ValueError:
            return False
    return True


def _matter_storage_layout_valid(path: Path) -> bool:
    """Inspect initialization names and existing marker metadata without probes or writes."""
    marker = path / ".recordbench-managed-storage.json"
    owned = tuple(path / name for name in ("matters", ".matter-purging", "ingestion-staging"))
    if not marker.exists() and not marker.is_symlink():
        return not any(entry.exists() or entry.is_symlink() for entry in owned)
    try:
        if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 4096:
            return False
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if (not isinstance(payload, dict) or payload.get("format_version") != 1
                or payload.get("product") != "RecordBench"
                or not isinstance(payload.get("storage_id"), str)
                or not payload["storage_id"].startswith("recordbench-storage-")):
            return False
        device = path.stat().st_dev
        return all(not entry.is_symlink() and entry.is_dir() and entry.stat().st_dev == device
                   and os.access(entry, os.R_OK | os.W_OK | os.X_OK) for entry in owned)
    except (OSError, ValueError):
        return False


def _storage_path_text_valid(path: Path) -> bool:
    return not any(ord(character) < 32 or ord(character) == 127 for character in str(path))


def _storage_roots_compatible(node: Path, storage: Path) -> bool:
    """Keep managed sources out of installer-owned state and control paths."""
    if not _storage_path_text_valid(node) or not _storage_path_text_valid(storage):
        return False
    try:
        node = node.expanduser().resolve(strict=False)
        storage = storage.expanduser().resolve(strict=False)
        if node.is_relative_to(storage):
            return False
        controls = [path for name, path in _paths(node).items() if name != "storage"]
        controls.extend(node / name for name in ("compose.env", "installation.json", "releases", "accounts"))
        return not any(storage.is_relative_to(control) for control in controls)
    except (OSError, ValueError):
        return False


def _collect_preflight(models: str, args: argparse.Namespace | None = None, *,
                       model_args: argparse.Namespace | None = None,
                       needs_model_staging: bool = True,
                       defer_gpu_free_check: bool = False) -> PreflightResult:
    checks: list[PreflightCheck] = []
    devices: tuple[GpuDevice, ...] = ()

    def add(name: str, passed: bool, observed: str, capability: str, remedy: str,
            *, blocking: bool = True) -> None:
        checks.append(PreflightCheck(name, "pass" if passed else "fail", observed,
                                     capability, blocking, "" if passed else remedy))

    supported = platform.system() == "Linux" and platform.machine().lower() in {"x86_64", "amd64"}
    add("host", supported, "Linux x86-64" if supported else "Unsupported operating system or architecture",
        "Run the Linux application node", "Use a dedicated x86-64 Linux host; this launcher does not provision other platforms.")
    if not supported:
        return PreflightResult(tuple(checks))
    add("ownership", os.geteuid() != 0 and os.getegid() != 0,
        "Non-root account and primary group" if os.geteuid() != 0 and os.getegid() != 0 else "Root account or primary group",
        "Own application state without running containers as root",
        "Run as a dedicated non-root service account with a non-root primary group. Have an administrator assign only the dedicated node and storage directories to it.")
    docker = shutil.which("docker") is not None
    add("docker", docker, "Docker CLI available" if docker else "Docker CLI missing",
        "Build and run application containers", "Install Docker Engine and the Compose v2 plugin using the Docker Linux installation instructions in docs/INSTALL.md.")
    for name, command, capability, remedy in (
        ("docker-access", ["docker", "info", "--format", "{{.ServerVersion}}"], "Access the container engine",
         "Start Docker and arrange approved engine access for the service account. Do not make the Docker socket world-writable; engine access is privileged."),
        ("compose", ["docker", "compose", "version", "--short"], "Run the application service definition",
         "Install the Docker Compose v2 plugin, then rerun this command as the service account."),
    ):
        if not docker:
            checks.append(PreflightCheck(name, "unknown", "Docker CLI is required to check this", capability, True, remedy))
            continue
        try:
            passed = _probe(command).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            passed = False
        add(name, passed, "Available" if passed else "Unavailable or diagnostic timed out", capability, remedy)
    openssl = shutil.which("openssl") is not None
    add("openssl", openssl, "OpenSSL available" if openssl else "OpenSSL missing",
        "Prepare HTTPS", "Install the distribution OpenSSL package; retain HTTPS and secure cookies.")

    options = model_args if model_args is not None else args
    if options is not None:
        try:
            languages = _transcription_languages(options.transcription_languages)
            _model_stage_groups(models, transcription_languages=languages,
                                diarization=bool(options.enable_diarization))
            model_options_ok = True
        except RuntimeError:
            model_options_ok = False
        add("model-options", model_options_ok,
            "Selected model options are compatible" if model_options_ok else "Selected model options conflict or use an unsupported language",
            "Stage the selected AI capabilities",
            "Choose --transcription-languages en, es, or en,es. Enable diarization only with --models transcription or all.")
        if (needs_model_staging and options.non_interactive
                and options.enable_diarization and models in {"transcription", "all"}):
            add("model-terms", bool(options.accept_model_terms),
                "Diarization terms acknowledged" if options.accept_model_terms else "Diarization terms acknowledgement missing",
                "Stage the selected gated speaker module",
                "Accept the selected model's terms, then pass --accept-model-terms.")
            add("model-token-input", bool(options.hf_token_stdin),
                "Token input selected; no token read" if options.hf_token_stdin else "One-time token input not selected",
                "Authorize one-time gated model staging without retaining credentials",
                "Pass --hf-token-stdin and supply a read-only token through controlled standard input when staging runs.")
    if args is not None:
        existing_resume = False
        if args.resume:
            try:
                _installed_release(args.root)
                existing_resume = True
            except RuntimeError:
                pass
        if not existing_resume and args.auth in {None, "local"}:
            # Keep the dependency-free launcher aligned with account-admin's
            # normalization; names are reported only as valid/invalid.
            login = (args.admin_username if args.admin_username is not None else "recordbench.admin").strip().casefold()
            display = (args.admin_display_name if args.admin_display_name is not None else "RecordBench Administrator").strip()
            identity_ok = (re.fullmatch(r"[a-z0-9][a-z0-9._@-]{2,127}", login) is not None
                           and bool(display) and len(display) <= 160
                           and not any(ord(character) < 32 for character in display))
            add("admin-identity", identity_ok,
                "Initial administrator identity is valid" if identity_ok else "Initial administrator identity is invalid",
                "Create the initial local administrator account",
                "Choose --admin-username with 3-128 letters, numbers, dots, dashes, underscores or @, starting with a letter or number. Choose a nonempty --admin-display-name of at most 160 characters without control characters.")
        if (args.non_interactive and not args.dry_run and not existing_resume
                and args.auth in {None, "local"}):
            add("admin-password-input", bool(args.password_stdin),
                "Password input selected; no password read" if args.password_stdin else "Initial administrator password input not selected",
                "Create the initial local administrator account",
                "Pass --password-stdin and supply the initial administrator password through controlled standard input when installation runs.")
        if not existing_resume:
            if args.auth in {"oidc", "kerberos"}:
                valid = _identity_options_valid(args)
                add("identity-options", valid,
                    "Identity provider settings are valid" if valid else "Identity provider settings are invalid",
                    "Configure an identity provider accepted by the runtime",
                    "Use an HTTPS issuer and non-loopback server name for OIDC, a nonempty client ID of at most 512 characters, and group names of at most 256 characters. Kerberos requires a dotted realm and at least one valid admission group. Limit allowed/admin groups to 100/50; omit control characters. See docs/INSTALL.md.")
            for auth, source, name, option in (
                ("oidc", args.oidc_client_secret_file, "oidc-secret-input", "--oidc-client-secret-file"),
                ("kerberos", args.kerberos_keytab, "kerberos-keytab-input", "--kerberos-keytab"),
            ):
                if args.auth == auth and (source is not None or (args.non_interactive and not args.dry_run)):
                    maximum_bytes = 4096 if auth == "oidc" else 1024 * 1024
                    available = _credential_source_available(source, maximum_bytes=maximum_bytes)
                    add(name, available,
                        "Credential source metadata is available; contents not read" if available else "Required credential source is missing or unsafe",
                        "Configure the selected identity provider",
                        f"Supply {option} as a readable nonempty regular file no larger than {maximum_bytes} bytes including line endings, without a symbolic link. Contents are not validated by this metadata check.")
            if args.auth == "kerberos" and not args.dry_run:
                host_join = Path("/var/lib/sss/pipes").is_dir() and Path("/etc/krb5.conf").is_file()
                add("kerberos-host", host_join,
                    "Host SSSD and Kerberos configuration paths are present" if host_join else "Host SSSD or Kerberos configuration is missing",
                    "Connect the Kerberos gateway to the host identity service",
                    "Complete the host SSSD/NSS join and Kerberos configuration before installation. Presence checks do not prove a working identity exchange.")
        storage_root = args.storage_root or args.root / "matter-storage"
        compatible = _storage_roots_compatible(args.root, storage_root)
        add("storage-separation", compatible,
            "Managed storage is separate from node control paths" if compatible else "Managed storage overlaps node control paths or uses an invalid path",
            "Keep source storage separate from installation configuration",
            "Use the default matter-storage directory, a separate dedicated directory, or a custom child outside config, secrets, runtime, transcription, state, models, tls, accounts, releases, compose.env and installation.json. Matter storage cannot equal or contain the node root.")
        for name, path in (("node-storage", args.root), ("matter-storage", storage_root)):
            entered_path = path.expanduser()
            try:
                lexical_path = Path(os.path.abspath(entered_path))
                safe = _storage_path_text_valid(entered_path) and entered_path.is_absolute() and not any(
                    part.is_symlink()
                    for part in (entered_path, *entered_path.parents, lexical_path, *lexical_path.parents)
                )
                # Match the canonical path installation will actually use while
                # retaining the refusal of symlinks in the entered path.
                path = entered_path.resolve(strict=False)
                # HOME may be inherited through sudo; consult the effective
                # service account too before accepting either storage root.
                import pwd
                effective_home = Path(pwd.getpwuid(os.geteuid()).pw_dir).resolve(strict=False)
                safe = safe and path not in {Path("/"), Path.home().resolve(strict=False), effective_home}
                ancestor = path
                while not ancestor.exists() and ancestor != ancestor.parent:
                    ancestor = ancestor.parent
                safe = safe and _storage_ancestors_safe(ancestor)
                if path.exists():
                    safe = safe and path.is_dir() and path.stat().st_uid == os.geteuid()
                writable = safe and os.access(ancestor, os.W_OK | os.X_OK)
                if name == "node-storage" and safe and path.is_dir():
                    empty_or_resume = existing_resume or not any(path.iterdir())
                    add("node-empty", empty_or_resume,
                        "Existing root can be prepared" if empty_or_resume else "Installation root already contains files",
                        "Prepare a dedicated installation root",
                        "Choose a new empty node directory. Use --resume only when this directory belongs to the RecordBench node being resumed.")
                add(name, writable, "Directory access checks pass (no write attempted)" if writable else "Unsafe path, ownership, or directory access",
                    "Create private application state" if name == "node-storage" else "Store and process admitted sources",
                    "Choose a dedicated absolute directory without symlinks or control characters, owned by the service account. Use an existing service-owned creation directory without group or other write access, beneath root-owned or service-owned protected parents. The service account needs read and search access to every ancestor; do not use a home directory or shared export root.")
                if name == "matter-storage" and writable:
                    layout_ok = _matter_storage_layout_valid(path)
                    add("matter-storage-layout", layout_ok,
                        "Managed storage initialization metadata is compatible" if layout_ok else "Managed storage initialization names conflict or existing metadata is invalid",
                        "Initialize or reopen the managed source boundary",
                        "Choose an empty dedicated matter storage root, or an intact initialized RecordBench storage root. Without a valid marker, matters, .matter-purging and ingestion-staging must not exist; do not delete existing data to bypass this check.")
                free = shutil.disk_usage(ancestor).free / (1024 ** 3) if safe else None
                add(name + "-reserve", free is not None and free > 100,
                    f"{free:.1f} GiB free" if free is not None else "Capacity could not be checked safely",
                    "Admit sources above the configured 100 GiB storage reserve",
                    "Provide more than 100 GiB free on this filesystem, plus capacity for images, models and matter data. See profile targets in docs/INSTALL.md.")
                target = {"none": 150, "review": 200, "transcription": 300, "all": 300}[models]
                if name == "node-storage":
                    add("capacity-target", free is not None and free >= target,
                        f"Alpha evaluation target: {target} GiB before matter data",
                        "Leave headroom for images and selected models",
                        "Plan additional SSD capacity for the selected profile. These evaluation targets are not validated minimums.", blocking=False)
            except (OSError, RuntimeError, KeyError, ValueError):
                add(name, False, "Directory metadata unavailable", "Inspect storage before installation",
                    "Ask the storage administrator to restore directory access, then rerun preflight.")
        try:
            _valid_host(args.server_name or "recordbench.example.test")
            server_name_ok = True
        except RuntimeError:
            server_name_ok = False
        add("server-name", server_name_ok,
            "Server name is valid" if server_name_ok else "Server name is invalid",
            "Configure the HTTPS gateway identity",
            "Choose --server-name using letters, digits, dots and hyphens, starting and ending with a letter or digit.")
        bind = args.bind_address if args.bind_address is not None else "127.0.0.1"
        try:
            ipaddress.ip_address(bind)
            bind_ok = "%" not in bind and not any(ord(character) < 32 for character in bind)
        except ValueError:
            bind_ok = False
        add("bind-address", bind_ok,
            "Bind address is an IP literal" if bind_ok else "Bind address is invalid",
            "Bind the private HTTPS gateway",
            "Use --bind-address with an IPv4 or unbracketed, unscoped IPv6 literal, without a hostname, port or control characters. Set the port separately with --https-port.")
        pair = bool(args.tls_cert) == bool(args.tls_key)
        supplied = bool(args.tls_cert and args.tls_key)
        readable = supplied and all(path.is_file() and not path.is_symlink() and os.access(path, os.R_OK)
                                    for path in (args.tls_cert, args.tls_key))
        tls_ok = pair and (readable if supplied else bind in {"127.0.0.1", "::1"})
        add("tls", tls_ok, "Readable supplied TLS pair; trust must be verified" if readable else
            "Loopback smoke certificate will be generated during installation" if tls_ok else "TLS choice incomplete or files unavailable",
            "Reach the private HTTPS gateway with secure sessions",
            "Supply both --tls-cert and --tls-key as readable regular files. LAN binding requires an organization-trusted pair; use the default loopback bind for local evaluation.")
        add("https-port", 1 <= args.https_port <= 65535, "Valid port" if 1 <= args.https_port <= 65535 else "Invalid port",
            "Bind the HTTPS gateway", "Choose --https-port between 1 and 65535.")

    if not _required_gpu_count(models):
        try:
            _resolve_gpu_plans(options or _parser().parse_args(["--models", models]), models, ())
            gpu_options_ok = True
        except RuntimeError:
            gpu_options_ok = False
        add("gpu-options", gpu_options_ok,
            "GPU option syntax is valid for CPU evaluation" if gpu_options_ok else "GPU option values or selections conflict",
            "Configure the selected CPU evaluation profile",
            "Remove GPU overrides when using --models none, or choose values accepted by the GPU/model options. CPU evaluation does not require a GPU.")
        checks.append(PreflightCheck("gpu", "pass", "GPU optional for CPU evaluation",
            "Intake, extraction, OCR, word search, source review and exports; no generated answers or transcription",
            False, ""))
    else:
        try:
            if shutil.which("nvidia-smi") is None:
                raise RuntimeError("NVIDIA driver diagnostic unavailable")
            inventory = _probe(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free,compute_cap", "--format=csv,noheader,nounits"])
            if inventory.returncode:
                raise RuntimeError("NVIDIA driver diagnostic failed")
            devices = _parse_gpu_inventory(inventory.stdout)
            if not devices or any(device.compute_capability is None for device in devices):
                raise RuntimeError("GPU inventory or compute capability unavailable")
            plan_args = options or _parser().parse_args(["--models", models])
            # An update has not stopped its current models yet. Check physical
            # compatibility here, retaining the real inventory in the result.
            # Actual free-memory admission remains mandatory after its own
            # runtime stops; this internal option is never a CLI bypass.
            planning_devices = (tuple(replace(device, free_mib=device.total_mib) for device in devices)
                                if defer_gpu_free_check else devices)
            _resolve_gpu_plans(plan_args, models, planning_devices)
            add("gpu", True,
                "Saved GPU plan fits physical capacity; actual free-memory admission is deferred until this node stops"
                if defer_gpu_free_check else "Selected GPU and model plan fits current reported hardware",
                "Run the selected local AI tasks", "")
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            add("gpu", False, "Selected GPU/model plan unavailable, incompatible, or short of free memory",
                "Generate cited answers" if models == "review" else "Transcribe recordings" if models == "transcription" else "Generate cited answers and transcribe recordings",
                "Install the NVIDIA driver and Container Toolkit; provide compute capability 7.5 or newer and sufficient free VRAM for the selected model/GPU options. Saved bfloat16 precision requires 8.0 or newer on every generator GPU. Stop competing GPU work or choose a smaller model. Use --models none for CPU evaluation.")
        # Check the engine configuration without pulling an image or launching a
        # container. Actual offline model/container readiness is a later gate.
        try:
            runtime_probe = _probe(["docker", "info", "--format", "{{json .Runtimes}}"] ) if docker else None
            runtimes = json.loads(runtime_probe.stdout) if runtime_probe and runtime_probe.returncode == 0 else None
            registered = isinstance(runtimes, dict) and "nvidia" in runtimes
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
            registered = False
        add("gpu-runtime", bool(registered), "NVIDIA runtime registered" if registered else "NVIDIA runtime registration not confirmed",
            "Make NVIDIA devices available to model containers",
            "Install and configure NVIDIA Container Toolkit for Docker using docs/INSTALL.md, then restart Docker through the approved operator procedure.")
    return PreflightResult(tuple(checks), devices)


def _render_preflight(console: Console, result: PreflightResult) -> None:
    console.phase(1, "HOST HANDSHAKE", "Read-only prerequisites; no state created or services started")
    for check in result.checks:
        marker = "OK" if check.state == "pass" else "BLOCK" if check.blocking else "NOTE"
        console.line(f"  [{marker}] {check.name}: {check.observed}")
        console.line(f"          Enables: {check.required_capability}")
        if check.remedy:
            console.line(f"          Next: {check.remedy}")
    console.line("  Prerequisites pass; installation and acceptance are still required." if result.ready else
                 "  Resolve blocking items and rerun ./install preflight with the same options.")


def _preflight(console: Console, *, models: str, dry_run: bool,
               args: argparse.Namespace | None = None,
               model_args: argparse.Namespace | None = None,
               needs_model_staging: bool = True,
               defer_gpu_free_check: bool = False) -> tuple[GpuDevice, ...]:
    result = _collect_preflight(models, args, model_args=model_args,
                                needs_model_staging=needs_model_staging,
                                defer_gpu_free_check=defer_gpu_free_check)
    _render_preflight(console, result)
    if not result.ready:
        raise RuntimeError("installation prerequisites are incomplete; see the checklist above")
    return result.devices


def _paths(root: Path, storage_root: Path | None = None) -> dict[str, Path]:
    return {
        "config": root / "config",
        "secrets": root / "secrets",
        "runtime": root / "runtime",
        "storage": storage_root or root / "matter-storage",
        "transcription": root / "transcription",
        "state": root / "state",
        "models": root / "models",
        "tls": root / "tls",
    }


def _mkdir_private(component: str, *, dir_fd: int) -> None:
    """Create relative to a held parent with owner access under any caller umask.

    Umask is process-global: change it only in an isolated child, before mkdir.
    The child inherits one already-validated directory descriptor and does not
    traverse an attacker-supplied path or repair permissions through a pathname.
    """
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c",
         "import os,sys\nos.umask(0)\n"
         "try: os.mkdir(sys.argv[1], 0o700, dir_fd=int(sys.argv[2]))\n"
         "except FileExistsError: sys.exit(17)\n"
         "except OSError: sys.exit(1)\n",
         component, str(dir_fd)],
        pass_fds=(dir_fd,), stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    if result.returncode == 17:
        raise FileExistsError("storage component was created concurrently")
    if result.returncode:
        raise OSError("storage component could not be created privately")


def _create_private_directory(path: Path) -> None:
    """Walk held, non-symlink directory descriptors and create each component privately.

    No path-based chmod can follow a replacement symlink. Existing ancestors are
    revalidated at use, and only the selected leaf is tightened to owner-only.
    """
    uid = os.geteuid()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        components = path.parts[1:]
        for index, component in enumerate(components):
            parent = os.fstat(descriptor)
            if parent.st_uid not in {0, uid} or (
                parent.st_mode & 0o022 and not parent.st_mode & stat.S_ISVTX
            ):
                raise RuntimeError("storage parent is replaceable by another account")
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if parent.st_uid != uid or parent.st_mode & 0o022:
                    raise RuntimeError("storage creation directory must be service-owned and protected")
                # The child preserves owner access even when umask masks 0700.
                try:
                    _mkdir_private(component, dir_fd=descriptor)
                except FileExistsError:
                    pass  # Revalidate a concurrently created entry below.
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            metadata = os.fstat(descriptor)
            if metadata.st_uid not in {0, uid} or (
                metadata.st_mode & 0o022 and not metadata.st_mode & stat.S_ISVTX
            ):
                raise RuntimeError("storage directory is replaceable by another account")
            if index == len(components) - 1:
                if metadata.st_uid != uid or metadata.st_mode & 0o022:
                    raise RuntimeError("selected storage must be service-owned and protected")
                os.fchmod(descriptor, 0o700)
    except OSError as exc:
        raise RuntimeError("storage directory changed or could not be prepared safely") from exc
    finally:
        os.close(descriptor)


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
    selected_storage = storage_root.expanduser() if storage_root else None
    for selected in (root, selected_storage):
        if selected is not None and any(part.is_symlink() for part in (selected, *selected.parents)):
            raise RuntimeError("storage paths cannot contain symbolic links")
    selected_storage = selected_storage.resolve(strict=False) if selected_storage else None
    if selected_storage is not None and (
        not selected_storage.is_absolute() or selected_storage == Path("/")
    ):
        raise RuntimeError("--storage-root must be an exact absolute directory other than /")
    if selected_storage is not None and selected_storage.exists() and selected_storage.is_symlink():
        raise RuntimeError("matter storage root cannot be a symbolic link")
    paths = _paths(root, selected_storage)
    if not dry_run:
        _create_private_directory(root)
        for value in paths.values():
            _create_private_directory(value)
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
    auth = args.auth
    if auth not in IDENTITY_FIELDS:
        raise RuntimeError("identity choices must be collected and checked before configuration")
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
        app_values["CASE_INTELLIGENCE_LOCAL_ACCOUNTS_FILE"] = "/run/recordbench-secrets/local-accounts.json"
        admin_username = args.admin_username
        admin_display = args.admin_display_name
    elif auth == "oidc":
        app_values.update(
            {
                "CASE_INTELLIGENCE_EXTERNAL_ORIGIN": f"https://{server_name}" + (f":{args.https_port}" if args.https_port != 443 else ""),
                "CASE_INTELLIGENCE_OIDC_ISSUER": args.oidc_issuer,
                "CASE_INTELLIGENCE_OIDC_CLIENT_ID": args.oidc_client_id,
                "CASE_INTELLIGENCE_OIDC_CLIENT_SECRET_FILE": "/run/recordbench-secrets/oidc-client-secret",
                "CASE_INTELLIGENCE_OIDC_ALLOWED_GROUPS": args.oidc_allowed_groups,
                "CASE_INTELLIGENCE_OIDC_ADMIN_GROUPS": args.oidc_admin_groups,
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
        realm = args.kerberos_realm.strip().upper()
        compose_values["RECORDBENCH_KERBEROS_PRINCIPAL"] = f"HTTP/{server_name}@{realm}"
        app_values.update(
            {
                "CASE_INTELLIGENCE_KERBEROS_REALM": realm,
                "CASE_INTELLIGENCE_KERBEROS_ALLOWED_GROUPS": args.kerberos_allowed_groups,
                "CASE_INTELLIGENCE_KERBEROS_ADMIN_GROUPS": args.kerberos_admin_groups,
                "CASE_INTELLIGENCE_KERBEROS_PROXY_SECRET_FILE": "/run/recordbench-secrets/kerberos-proxy-secret",
            }
        )
        if not args.dry_run:
            _secret(paths["secrets"] / "kerberos-proxy-secret")
            target_keytab = paths["secrets"] / "recordbench.keytab"
            if not target_keytab.exists():
                source_keytab = args.kerberos_keytab
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
    compose = _compose(root, profiles)

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
    if auth == "local" and not (root / "secrets" / "local-accounts.json").exists():
        if not admin_username or not admin_display:
            raise RuntimeError(
                "unfinished local installation requires --admin-username and "
                "--admin-display-name when resumed"
            )
        password = "dry-run-password-placeholder" if args.dry_run else _password(args)
        try:
            _run(
                console,
                [*compose, "run", "--rm", "--no-deps", "-T", "account-admin", "accounts", "init", "--file", "/run/recordbench-secrets/local-accounts.json", "--username", str(admin_username), "--display-name", str(admin_display), "--password-stdin"],
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
            token = "dry-run-token-placeholder" if args.dry_run else _hf_token(args)
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
    runtime_compose = _compose(root, active)
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


def _restore_model_options(
    args: argparse.Namespace,
    installation: Mapping[str, object],
    compose_env: Mapping[str, str],
    transcription_env: Mapping[str, str],
) -> None:
    """Validate the saved deployment's choices, never substitute an automatic plan."""
    languages = installation.get("transcription_languages", ["en"])
    topology = installation.get("gpu_topology", {})
    if (not isinstance(languages, list)
            or not all(isinstance(value, str) for value in languages)
            or not isinstance(topology, dict)):
        raise RuntimeError("installed model metadata is invalid")
    generator = topology.get("generator", [])
    if not isinstance(generator, list) or not all(isinstance(value, str) for value in generator):
        raise RuntimeError("installed GPU metadata is invalid")
    args.transcription_languages = ",".join(languages)
    args.enable_diarization = bool(installation.get("transcription_diarization", False))
    args.review_model_profile = str(installation.get("review_model_profile", "portable"))
    args.gpu_layout = compose_env.get("RECORDBENCH_GPU_LAYOUT", str(installation.get("gpu_layout", "shared")))
    args.generator_gpus = compose_env.get("RECORDBENCH_GENERATOR_GPU", ",".join(generator)) or None
    # Match Compose's default when an older environment omits this setting.
    args.generator_dtype = compose_env.get("RECORDBENCH_GENERATOR_DTYPE") or "bfloat16"
    args.transcription_gpu = compose_env.get("RECORDBENCH_TRANSCRIPTION_GPU", topology.get("transcription"))
    args.retrieval_device = compose_env.get("RECORDBENCH_RETRIEVAL_DEVICE", str(topology.get("retrieval_device", "cpu")))
    args.retrieval_gpu = (compose_env.get("RECORDBENCH_RETRIEVAL_GPU", topology.get("retrieval_gpu"))
                          if args.retrieval_device == "cuda" else None)
    models = str(installation.get("models", "none"))
    if (args.review_model_profile not in {"portable", "quality"}
            or (models in {"review", "all"} and not args.generator_gpus)
            or (models in {"transcription", "all"} and not args.transcription_gpu)
            or (args.retrieval_device == "cuda" and not args.retrieval_gpu)):
        raise RuntimeError("installed model/GPU selections are incomplete")
    try:
        utilization = compose_env.get("RECORDBENCH_GENERATOR_GPU_UTILIZATION")
        args.generator_gpu_utilization = float(utilization) if utilization is not None else None
        minimum_free = transcription_env.get("TRANSCRIPTION_V2_MIN_FREE_VRAM_MB")
        args.transcription_min_free_vram_mib = int(minimum_free) if minimum_free is not None else None
    except (TypeError, ValueError) as exc:
        raise RuntimeError("installed GPU capacity settings are invalid") from exc


def _resume_node(console: Console, args: argparse.Namespace, root: Path) -> None:
    installation, _release = _installed_release(root)
    auth = str(installation.get("auth", ""))
    models = str(installation.get("models", "none"))
    _restore_model_options(args, installation, _dotenv(root / "compose.env"),
                           _dotenv(root / "config" / "transcription.env") if models in {"transcription", "all"} else {})
    profiles = installation.get("profiles", [])
    if (
        auth not in {"local", "oidc", "kerberos"}
        or models not in {"none", "review", "transcription", "all"}
        or not isinstance(profiles, list)
    ):
        raise RuntimeError("installed node metadata is invalid")
    complete = _provisioning_complete(root, installation)
    _preflight(console, models=models, dry_run=args.dry_run, model_args=args,
               needs_model_staging=not complete)
    console.phase(2, "REJOIN NODE", "Using sealed identity, storage, model, and release coordinates")
    compose = _compose(root, profiles)
    _run(console, [*compose, "config", "--quiet"], dry_run=args.dry_run)
    console.ok(f"release capsule :: {installation.get('release_id', 'legacy')}")
    if not complete:
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
    _restore_model_options(args, installation, _dotenv(root / "compose.env"),
                           _dotenv(root / "config" / "transcription.env") if models in {"transcription", "all"} else {})
    _preflight(console, models=models, dry_run=args.dry_run, model_args=args,
               needs_model_staging=False, defer_gpu_free_check=True)
    old_compose = _compose(root, profiles, release=old_release, auth=auth)
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
        _run(console, [*compose, "config", "--quiet"], dry_run=args.dry_run)
        console.phase(5, "ATOMIC NODE SWAP", "Starting the new capsule and waiting for application and storage consensus")
        if _required_gpu_count(models):
            console.note("Stopping this node to release its model allocation before checking actual free GPU memory")
            _run(console, [*old_compose, "stop", "--timeout", "120"], dry_run=args.dry_run)
            if args.dry_run:
                console.note("Dry run: actual free-memory admission is deferred until the node is stopped during update")
            else:
                # Never assume that all used VRAM belongs to this node: after
                # its scoped stop, competing allocations remain in this probe.
                _preflight(console, models=models, dry_run=False, model_args=args,
                           needs_model_staging=False)
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
    console = Console(
        color=sys.stdout.isatty() and not args.no_color and os.getenv("NO_COLOR") is None,
        quiet=args.quiet,
    )
    if args.json and args.command != "preflight":
        _parser().error("--json is only supported by the preflight command")
    if args.command == "preflight":
        args.root = (args.root or Path("/srv/recordbench")).expanduser()
        result = _collect_preflight(args.models or "none", args)
        if args.json:
            print(json.dumps(result.payload(), indent=2))
        else:
            _render_preflight(console, result)
        return 0 if result.ready else 1
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
        if not _storage_path_text_valid(args.root):
            raise RuntimeError("installation root cannot contain control characters")
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
        if args.storage_root is None and not args.non_interactive:
            args.storage_root = Path(
                _ask(
                    "Managed matter storage root",
                    str(root / "matter-storage"),
                    non_interactive=False,
                )
            )
        if args.bind_address is None and not args.non_interactive:
            args.bind_address = _ask("HTTPS bind address", "127.0.0.1", non_interactive=False)
        if not args.server_name:
            args.server_name = _ask(
                "RecordBench hostname", "recordbench.example.test", non_interactive=args.non_interactive
            )
        # Reject an invalid hostname before asking unrelated identity questions.
        _valid_host(args.server_name)
        _collect_identity_choices(args)
        args.root = args.root.expanduser()
        # Resolve storage, TLS and the complete hardware plan before creating
        # state. Dry-run discovery uses the same read-only prerequisite checks.
        gpu_devices = _preflight(console, models=models, dry_run=args.dry_run, args=args)
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
