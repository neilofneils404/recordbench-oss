"""Content-versioned static asset URLs.

Pages reference stylesheets and scripts as ``/static/<name>?v=<digest>``. The
digest changes whenever the file changes, so a browser never pairs new page
markup with a stylesheet or script cached from an earlier release.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

STATIC_ROOT = Path(__file__).resolve().parent / "static"
VERSION_LENGTH = 12
VERSIONED_CACHE_CONTROL = "public, max-age=31536000, immutable"
UNVERSIONED_CACHE_CONTROL = "no-cache"

_digests: dict[str, tuple[int, int, str]] = {}


def _static_file(name: str) -> Path | None:
    relative = name.lstrip("/")
    if not relative:
        return None
    candidate = (STATIC_ROOT / relative).resolve()
    if not candidate.is_relative_to(STATIC_ROOT) or not candidate.is_file():
        return None
    return candidate


def asset_version(name: str) -> str | None:
    """Return the short content digest for a static file, or None if absent."""
    path = _static_file(name)
    if path is None:
        return None
    stat = path.stat()
    key = str(path)
    cached = _digests.get(key)
    if cached is not None and cached[:2] == (stat.st_mtime_ns, stat.st_size):
        return cached[2]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:VERSION_LENGTH]
    _digests[key] = (stat.st_mtime_ns, stat.st_size, digest)
    return digest


def asset_url(name: str) -> str:
    """Return the public URL for a static file, versioned by its content."""
    relative = name.lstrip("/")
    version = asset_version(relative)
    url = f"/static/{relative}"
    return f"{url}?v={version}" if version else url


def static_cache_control(path: str, query_version: str | None) -> str:
    """Cache forever only when the requested version matches current content."""
    name = path.removeprefix("/static/")
    if query_version and query_version == asset_version(name):
        return VERSIONED_CACHE_CONTROL
    return UNVERSIONED_CACHE_CONTROL
