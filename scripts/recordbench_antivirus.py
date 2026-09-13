"""Bounded, operator-requested antivirus configuration and signed CVD import."""
from __future__ import annotations

import os
import json
import re
import shlex
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlsplit


CONFIG_KEY = "RECORDBENCH_CLAMAV_CONFIG"
CONFIG_NAME = "clamav-freshclam.conf"
DATABASES = ("main.cvd", "daily.cvd", "bytecode.cvd")
MAX_DATABASE_BYTES = 512 * 1024 * 1024
DEFAULT_CONFIG = """# RecordBench managed antivirus updater.
DatabaseDirectory /var/lib/clamav
DatabaseOwner clamav
TestDatabases yes
ConnectTimeout 15
ReceiveTimeout 60
MaxAttempts 2
LogTime yes
"""


def _network_url(value: str, *, proxy: bool = False) -> str:
    if not value or len(value) > 2048 or re.search(r"[\s\x00-\x1f\x7f\\#$]", value):
        raise RuntimeError("antivirus network address is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("antivirus network address is invalid") from exc
    if (parsed.scheme not in ({"http"} if proxy else {"http", "https"})
            or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or (proxy and parsed.path not in {"", "/"})
            or port is not None and not 1 <= port <= 65535):
        raise RuntimeError("use an HTTP(S) mirror or HTTP proxy without credentials, query or fragment")
    if re.fullmatch(r"[A-Za-z0-9.:-]+", parsed.hostname) is None:
        raise RuntimeError("antivirus network hostname is invalid")
    return value.rstrip("/")


def configuration(mirror: str | None, proxy: str | None) -> str:
    result = DEFAULT_CONFIG
    if mirror:
        result += f"PrivateMirror {_network_url(mirror)}\nScriptedUpdates no\n"
    else:
        result += "DatabaseMirror database.clamav.net\nScriptedUpdates yes\n"
    if proxy:
        parsed = urlsplit(_network_url(proxy, proxy=True))
        result += f"HTTPProxyServer {parsed.hostname}\nHTTPProxyPort {parsed.port or 80}\n"
    return result


def validate_saved(root: Path, environment: dict[str, str], installer) -> None:
    selected = environment.get(CONFIG_KEY)
    if selected is None:
        return  # Existing/default nodes use the reviewed release's default file.
    expected = root / "config" / CONFIG_NAME
    if selected != str(expected):
        raise RuntimeError("saved antivirus configuration must use its canonical node file")
    content = installer._credential_source_content(expected, private=True)
    if content is None or len(content) > 8192:
        raise RuntimeError("saved antivirus configuration is unavailable or unsafe")
    try:
        value = content.decode("utf-8")
        rows = dict(line.split(" ", 1) for line in value.splitlines() if line and not line.startswith("#"))
        mirror = rows.get("PrivateMirror")
        proxy = None
        if "HTTPProxyServer" in rows:
            host = rows["HTTPProxyServer"]
            host = f"[{host}]" if ":" in host else host
            proxy = f"http://{host}:{rows['HTTPProxyPort']}"
        if value != configuration(mirror, proxy):
            raise ValueError("unexpected configuration")
    except (ValueError, KeyError, UnicodeError) as exc:
        raise RuntimeError("saved antivirus configuration has unsupported directives; regenerate it with the antivirus command") from exc


def _open_protected_directory(source: Path) -> int:
    if not source.is_absolute() or ".." in source.parts:
        raise RuntimeError("signature source must have protected, non-symlink root/service-owned ancestry")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in (*source.parts[1:], None):
            metadata = os.fstat(descriptor)
            mode = stat.S_IMODE(metadata.st_mode)
            sticky = component is not None and metadata.st_uid == 0 and mode == 0o1777
            if metadata.st_uid not in {0, os.geteuid()} or mode & 0o022 and not sticky:
                raise RuntimeError("signature source ancestry must be protected and root/service-owned")
            if component is not None:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def _operation_lock(root: Path):
    import fcntl
    directory = _open_protected_directory(root / "state")
    descriptor = None
    try:
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            descriptor = os.open(".antivirus-operation.lock", flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
            os.fchmod(descriptor, 0o600)
        except FileExistsError:
            descriptor = os.open(".antivirus-operation.lock", flags, dir_fd=directory)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RuntimeError("antivirus operation lock is unsafe")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another antivirus preparation or recovery operation is active") from exc
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


def _snapshot(source: Path, target: Path, installer) -> None:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    directory = _open_protected_directory(source)
    try:
        for name in DATABASES:
            descriptor = os.open(name, flags, dir_fd=directory)
            try:
                before = os.fstat(descriptor)
                if (not stat.S_ISREG(before.st_mode) or before.st_uid not in {0, os.geteuid()}
                        or before.st_mode & 0o022 or not 512 < before.st_size <= MAX_DATABASE_BYTES):
                    raise RuntimeError("signature source needs three protected regular signed CVD files within size limits")
                with os.fdopen(descriptor, "rb", closefd=False) as incoming, (target / name).open("xb") as outgoing:
                    header = incoming.read(512)
                    try:
                        fields = header.decode("ascii").rstrip(" ").split(":")
                        if len(fields) != 9 or fields[0] != "ClamAV-VDB" or not fields[8].isdigit():
                            raise ValueError("invalid header")
                        built = int(fields[8])
                    except (ValueError, UnicodeError) as exc:
                        raise RuntimeError("signature CVD header is invalid") from exc
                    if name == "daily.cvd" and not time.time() - 259200 <= built <= time.time() + 300:
                        raise RuntimeError("daily signatures are stale or future-dated; file timestamps do not establish freshness")
                    outgoing.write(header)
                    remaining = before.st_size - len(header)
                    while remaining:
                        chunk = incoming.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise RuntimeError("signature source changed during snapshot")
                        outgoing.write(chunk)
                        remaining -= len(chunk)
                    if incoming.read(1) or installer._read_identity(before) != installer._read_identity(os.fstat(descriptor)):
                        raise RuntimeError("signature source changed during snapshot")
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                os.chmod(target / name, 0o600)
            finally:
                os.close(descriptor)
    finally:
        os.close(directory)


def run(console, args, root: Path, installer) -> None:
    if args.dry_run:
        return _run_locked(console, args, root, installer)
    # Validate node coordinates before opening the private operation lock.
    installer._saved_node_arguments(args, root, validate_antivirus=bool(args.import_signatures))
    with _operation_lock(root):
        return _run_locked(console, args, root, installer)


def _run_locked(console, args, root: Path, installer) -> None:
    mirror, proxy = args.antivirus_mirror, args.antivirus_proxy
    if args.import_signatures and (mirror or proxy or args.reset_antivirus):
        raise RuntimeError("configure updater access and import signatures in separate commands")
    if args.reset_antivirus and (mirror or proxy):
        raise RuntimeError("reset cannot be combined with a mirror or proxy")
    if not (args.import_signatures or mirror or proxy or args.reset_antivirus):
        raise RuntimeError("choose --antivirus-mirror, --antivirus-proxy, --reset-antivirus or --import-signatures")
    prepared = None if args.import_signatures else configuration(mirror, proxy)
    settings, release = installer._saved_node_arguments(args, root, validate_antivirus=prepared is None)
    if not (release / "deploy/clamav/import-signatures.sh").is_file():
        raise RuntimeError("the installed release predates antivirus recovery; update to a reviewed release containing it first")
    compose = installer._compose(root, settings["profiles"])
    if not args.dry_run:
        observed = installer._run(console, [*compose, "ps", "--all", "--format", "json"], capture=True)
        try:
            try:
                containers = json.loads(observed.stdout) if observed.stdout.strip() else []
            except json.JSONDecodeError:
                containers = [json.loads(line) for line in observed.stdout.splitlines() if line.strip()]
            if isinstance(containers, dict):
                containers = [containers]
            stopped = isinstance(containers, list) and all(isinstance(row, dict) and row.get("State") in {"exited", "created"} for row in containers)
        except (ValueError, TypeError):
            stopped = False
        if not stopped:
            raise RuntimeError("stop this node before antivirus changes: " + shlex.join([*compose, "stop"]))
    if prepared is not None:
        console.note("Configure the node's signature updater; scanner network isolation is unchanged")
        if not args.dry_run:
            installer._atomic_private_write(root / "config" / CONFIG_NAME, prepared)
            installer._replace_env(root / "compose.env", CONFIG_KEY, str(root / "config" / CONFIG_NAME))
        console.ok("Antivirus configuration prepared; resume the node to verify a real update and scanner health")
        return
    if args.dry_run:
        console.note("Dry run: snapshot three signed CVD databases, verify signatures and engine loading offline, then import into this stopped node")
        return
    with tempfile.TemporaryDirectory(prefix=".clamav-import-", dir=root / "state") as temporary:
        staging = Path(temporary)
        _snapshot(args.import_signatures.expanduser(), staging, installer)
        if any(character in str(staging) for character in (":", ",", "\n", "\r")):
            raise RuntimeError("node path cannot be represented safely as an antivirus import mount")
        result = installer._run(console, [*compose, "run", "--rm", "--no-deps", "-T",
            "--volume", f"{staging}:/recordbench-import:ro", "clamav-import"], capture=True, check=False)
        if result.returncode != 0 or "signature-import-complete" not in result.stdout.splitlines():
            raise RuntimeError("offline signature import failed verification or loading; node remains stopped; retry a complete valid import before resume")
    console.ok("Signed signatures imported and loaded offline; resume to verify the scanner. Future updater access remains separate")


def prepare(console, root: Path, compose: list[str], installer, *, dry_run: bool = False) -> None:
    # A current launcher may resume an older capsule; keep its existing startup
    # path instead of trying to exec a helper that did not ship in that capsule.
    release = Path(compose[compose.index("-f") + 1]).parent if "-f" in compose else installer.PROJECT
    if not (release / "deploy/clamav/signature-health.sh").is_file():
        console.note("This older capsule uses its original antivirus startup checks; update to the current reviewed release for bounded recovery")
        return
    if dry_run:
        return _prepare_locked(console, root, compose, installer, dry_run=True)
    with _operation_lock(root):
        return _prepare_locked(console, root, compose, installer)


def _prepare_locked(console, root: Path, compose: list[str], installer, *, dry_run: bool = False) -> None:
    console.note("Preparing antivirus: waiting up to three minutes for current signature databases")
    installer._run(console, [*compose, "up", "-d", "clamav-updater"], dry_run=dry_run)
    if dry_run:
        return
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            result = installer._probe([*compose, "exec", "-T", "clamav-updater", "sh", "/opt/recordbench-antivirus/signature-health.sh"])
            if result.returncode == 0 and result.stdout.strip() == "signatures-fresh":
                console.ok("Current antivirus signatures are available; starting the scanner")
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
        time.sleep(3)
    reason = "signatures are missing, stale, or an import is incomplete"
    try:
        result = installer._probe([*compose, "logs", "--no-color", "--tail", "40", "clamav-updater"])
        log = (result.stdout + result.stderr).casefold()
        if "429" in log or "cool-down" in log or "cooldown" in log:
            reason = "the signature service requested a cooldown; honor its retry window"
        elif "403" in log or "1020" in log:
            reason = "signature downloads were blocked; configure approved mirror/proxy access"
        elif "timeout" in log or "timed out" in log or "timeout was reached" in log:
            reason = "the signature download timed out; check updater connectivity or configure a mirror"
        elif "resolve" in log:
            reason = "signature hostname resolution failed"
    except (OSError, subprocess.TimeoutExpired):
        pass
    raise RuntimeError("Antivirus preparation paused: " + reason + ". Updater state is retained; see docs/ANTIVIRUS_RECOVERY.md and resume after correcting the cause")
