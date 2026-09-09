"""Shared bounded local-account format validation for runtime and offline backup.

This module intentionally uses only the Python standard library. It performs
structural validation, not password authentication or filesystem authorization.
"""
from __future__ import annotations

import base64
import re
import unicodedata
from dataclasses import dataclass, field

_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._@-]{2,127}$")
_REVISION = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class LocalAccount:
    username: str
    display_name: str
    password_hash: str = field(repr=False)
    roles: frozenset[str] = frozenset()
    enabled: bool = True
    session_revision: str = field(default="legacy", repr=False)


def normalized_account(username: str, display_name: str) -> tuple[str, str]:
    login = (username or "").strip().casefold()
    display = unicodedata.normalize("NFC", (display_name or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    if _USERNAME.fullmatch(login) is None:
        raise RuntimeError("Username must be 3-128 lowercase letters, numbers, dots, dashes, underscores, or @")
    if not display or len(display) > 160 or any(unicodedata.category(value) in {"Cc", "Cf"} for value in display):
        raise RuntimeError("Display name is missing or invalid")
    return login, display


def validate_password_hash(value: str) -> None:
    """Validate a PHC Argon2id encoding without executing its password work.

    The operator backup tool uses only the standard library. Runtime readers
    additionally validate parameters with argon2-cffi before caching accounts.
    """
    match = re.fullmatch(
        r"\$argon2id\$(?:v=(16|19)\$)?m=([0-9]+),t=([0-9]+),p=([0-9]+)"
        r"\$([A-Za-z0-9+/]+)\$([A-Za-z0-9+/]+)", value,
    )
    if match is None:
        raise RuntimeError("Local account file contains an invalid password hash")
    _, memory, iterations, parallelism, salt, digest = match.groups()
    lanes = int(parallelism)
    if not (1 <= lanes <= 2**24 - 1 and 8 * lanes <= int(memory) <= 2**32 - 1
            and 1 <= int(iterations) <= 2**32 - 1):
        raise RuntimeError("Local account file contains invalid Argon2id parameters")
    for encoded, minimum in ((salt, 8), (digest, 4)):
        try:
            decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True)
        except ValueError as exc:
            raise RuntimeError("Local account file contains an invalid password hash") from exc
        if len(decoded) < minimum or base64.b64encode(decoded).decode().rstrip("=") != encoded:
            raise RuntimeError("Local account file contains an invalid password hash")


def parse_accounts(payload: object) -> tuple[int, dict[str, LocalAccount]]:
    if (not isinstance(payload, dict) or set(payload) != {"format_version", "accounts"}
            or type(payload.get("format_version")) is not int
            or payload["format_version"] not in {1, 2}
            or not isinstance(payload.get("accounts"), list)
            or not 1 <= len(payload["accounts"]) <= 500):
        raise RuntimeError("Local account file does not match the required format")
    version = payload["format_version"]
    accounts: dict[str, LocalAccount] = {}
    for raw in payload["accounts"]:
        allowed = {"username", "display_name", "password_hash", "roles", "enabled"}
        required = {"username", "display_name", "password_hash"}
        if version == 2:
            allowed.add("session_revision")
            required.add("session_revision")
        if not isinstance(raw, dict) or not set(raw).issubset(allowed) or not required.issubset(raw):
            raise RuntimeError("Local account file contains an invalid account")
        if not isinstance(raw["username"], str) or not isinstance(raw["display_name"], str):
            raise RuntimeError("Local account file contains an invalid account")
        username, display = normalized_account(raw["username"], raw["display_name"])
        password_hash = raw["password_hash"]
        roles = raw.get("roles", [])
        enabled = raw.get("enabled", True)
        revision = raw.get("session_revision", "legacy")
        if (not isinstance(password_hash, str) or not password_hash.startswith("$argon2id$")
                or len(password_hash) > 512 or not isinstance(roles, list)
                or any(value != "administrator" for value in roles)
                or len(set(roles)) != len(roles) or not isinstance(enabled, bool)
                or username in accounts
                or (version == 2 and (not isinstance(revision, str) or not _REVISION.fullmatch(revision)))):
            raise RuntimeError("Local account file contains an invalid account")
        validate_password_hash(password_hash)
        accounts[username] = LocalAccount(username, display, password_hash, frozenset(roles), enabled, revision)
    if not any(account.enabled and "administrator" in account.roles for account in accounts.values()):
        raise RuntimeError("At least one enabled local administrator is required")
    return version, accounts



def validate_frozen_account_file(path) -> None:
    """Check the required mode-0600 v2 store in an isolated mode-0700 copy."""
    import json
    import os
    import stat
    from pathlib import Path

    path = Path(path)
    if not path.is_absolute() or path.name != "local-accounts.json":
        raise RuntimeError("Frozen local account path is invalid")
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parent = os.fstat(directory)
        if parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) != 0o700:
            raise RuntimeError("Frozen local account directory must be owner-only with mode 0700")
        allowed = re.compile(r"^(?:local-accounts\.json|\.local-accounts\.json\.lock|\.local-accounts\.json-[0-9a-f]{32}\.tmp)$")
        for name in os.listdir(directory):
            item = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if (not allowed.fullmatch(name) or not stat.S_ISREG(item.st_mode)
                    or item.st_uid != os.geteuid() or stat.S_IMODE(item.st_mode) != 0o600):
                raise RuntimeError("Frozen local account directory contains an unsafe entry")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                    or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size > 1024 * 1024):
                raise RuntimeError("Frozen local account file is unavailable or unsafe")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise RuntimeError("Frozen local account file exceeds its size limit")
            version, _ = parse_accounts(json.loads(data.decode("utf-8")))
            if version != 2:
                raise RuntimeError("Browser account snapshots require version 2")
            after = os.fstat(descriptor)
            if ((before.st_dev, before.st_ino, before.st_mode, before.st_uid,
                 before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_mode, after.st_uid,
                        after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise RuntimeError("Frozen local account file changed during validation")
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


if __name__ == "__main__":
    import sys
    try:
        if len(sys.argv) != 2:
            raise RuntimeError("Supply the frozen account file")
        validate_frozen_account_file(sys.argv[1])
    except (OSError, RuntimeError, ValueError, UnicodeDecodeError):
        print("Frozen local account snapshot validation failed.", file=sys.stderr)
        raise SystemExit(1) from None
