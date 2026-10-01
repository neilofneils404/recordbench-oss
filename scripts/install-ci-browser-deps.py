#!/usr/bin/env python3
"""Bound package acquisition on the disposable Ubuntu browser CI runner."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import platform
import subprocess
import sys


PACKAGES = (
    "libnss3", "libatk-bridge2.0-0", "libxkbcommon0", "libxcomposite1",
    "libxdamage1", "libxrandr2", "libgbm1", "libasound2t64", "libgtk-3-0",
    "fonts-liberation", "ffmpeg",
)
MIRRORS = Path("/etc/apt/apt-mirrors.txt")
SOURCES = Path("/etc/apt/sources.list.d/ubuntu.sources")
OFFICIAL_MIRRORS = (
    "https://archive.ubuntu.com/ubuntu/",
    "https://security.ubuntu.com/ubuntu/",
)
ACQUIRE_OPTIONS = (
    "-o", "Acquire::Retries=1",
    "-o", "Acquire::http::Timeout=15",
    "-o", "Acquire::https::Timeout=15",
)


def acquire() -> bool:
    # Only acquisition is terminated by these deadlines, never dpkg unpacking.
    # Connection/data timeouts alone do not bound a continuously slow download.
    for seconds, arguments in (
        (60, ("update", "--error-on=any")),
        (180, ("install", "--yes", "--no-install-recommends", "--download-only", *PACKAGES)),
    ):
        result = subprocess.run([
            "sudo", "timeout", "--signal=TERM", "--kill-after=10s", f"{seconds}s",
            "apt-get", *ACQUIRE_OPTIONS, *arguments,
        ], check=False)
        if result.returncode:
            print(f"APT acquisition stopped with status {result.returncode}.", flush=True)
            return False
    return True


@contextmanager
def official_mirrors(mirrors: Path, sources: Path):
    """Temporarily select only official HTTPS entries already on this runner."""
    original = mirrors.read_bytes()
    existing = {
        line.split()[0] for line in original.decode().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if not set(OFFICIAL_MIRRORS).issubset(existing):
        raise ValueError("The runner's existing official HTTPS mirrors are unavailable.")
    source_uris = {
        uri for line in sources.read_text().splitlines()
        if line.startswith("URIs:") for uri in line.split()[1:]
    }
    if "mirror+file:/etc/apt/apt-mirrors.txt" not in source_uris:
        raise ValueError("The runner's Ubuntu sources do not use the expected mirror list.")
    replacement = "".join(
        f"{uri}\tpriority:{priority}\n"
        for priority, uri in enumerate(OFFICIAL_MIRRORS, start=1)
    ).encode()
    # Keep ubuntu.sources (suites, components, Signed-By) and APT trust untouched.
    # Restore even if a write, acquisition, or installation fails.
    try:
        subprocess.run(["sudo", "tee", str(mirrors)], input=replacement,
                       stdout=subprocess.DEVNULL, check=True)
        yield
    finally:
        subprocess.run(["sudo", "tee", str(mirrors)], input=original,
                       stdout=subprocess.DEVNULL, check=True)


def install() -> None:
    # No timeout/fallback around unpacking. Missing archives remain a hard error.
    subprocess.run([
        "sudo", "apt-get", "install", "--yes", "--no-install-recommends",
        "--no-download", *PACKAGES,
    ], check=True)


def install_dependencies(mirrors: Path = MIRRORS, sources: Path = SOURCES) -> None:
    print("Acquiring browser CI dependencies with bounded downloads.", flush=True)
    if acquire():
        install()
        return
    print("Retrying acquisition once with the existing official HTTPS mirrors.", flush=True)
    with official_mirrors(mirrors, sources):
        if not acquire():
            raise RuntimeError("Browser CI dependency acquisition failed on both attempts; nothing installed.")
        install()


def main() -> int:
    # This helper may change only the disposable hosted runner's mirror list.
    if sys.platform != "linux" or platform.machine() != "x86_64" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("This helper requires the Ubuntu 24.04 x86_64 GitHub Actions runner.")
    release = platform.freedesktop_os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise RuntimeError("This helper requires Ubuntu 24.04.")
    install_dependencies()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Browser CI dependency setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
