"""Content-free installation and identity administration commands."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from typing import Mapping

from .identity import LocalAccountSettings
from .managed_storage import ManagedMatterStorage, StoragePolicy


_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._@-]{2,127}$")


def _password_from_terminal(*, confirm: bool) -> str:
    if not sys.stdin.isatty():
        raise RuntimeError(
            "A terminal is required; use --password-stdin for unattended setup"
        )
    value = getpass.getpass("Password: ")
    if confirm and value != getpass.getpass("Confirm password: "):
        raise RuntimeError("Passwords did not match")
    return value


def _password_from_stdin() -> str:
    value = sys.stdin.readline(4_097)
    if not value or len(value) > 4_096:
        raise RuntimeError("Password input is missing or too large")
    return value.rstrip("\r\n")


def _validate_password(value: str) -> str:
    if not 14 <= len(value) <= 1_024:
        raise RuntimeError("Local account passwords must contain 14 to 1,024 characters")
    if "\x00" in value:
        raise RuntimeError("Local account password contains an invalid character")
    return value


def _normalized_account(username: str, display_name: str) -> tuple[str, str]:
    login = (username or "").strip().casefold()
    display = (display_name or "").strip()
    if _USERNAME.fullmatch(login) is None:
        raise RuntimeError(
            "Username must be 3-128 lowercase letters, numbers, dots, dashes, underscores, or @"
        )
    if not display or len(display) > 160 or any(ord(value) < 32 for value in display):
        raise RuntimeError("Display name is missing or invalid")
    return login, display


def _private_json(path: Path) -> dict[str, object]:
    candidate = Path(path)
    metadata = candidate.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.geteuid()
        or metadata.st_size > 1024 * 1024
    ):
        raise RuntimeError("Account file is unavailable or unsafe")
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Account file is invalid")
    return payload


def _write_private_json(path: Path, payload: Mapping[str, object], *, create: bool) -> None:
    candidate = Path(path)
    if not candidate.is_absolute() or candidate == Path("/"):
        raise RuntimeError("Account file must be an exact absolute path")
    candidate.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if candidate.parent.is_symlink() or any(parent.is_symlink() for parent in candidate.parents):
        raise RuntimeError("Account file path cannot traverse a symbolic link")
    if create and (candidate.exists() or candidate.is_symlink()):
        raise RuntimeError("Account file already exists")
    if not create:
        _private_json(candidate)
    temporary = candidate.parent / f".{candidate.name}-{uuid.uuid4().hex}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=True, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, candidate)
        directory = os.open(candidate.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _hash_password(value: str) -> str:
    try:
        from argon2 import PasswordHasher
    except ImportError as exc:
        raise RuntimeError("Argon2 support is unavailable") from exc
    return PasswordHasher().hash(_validate_password(value))


def _account_payload(
    username: str,
    display_name: str,
    password: str,
    *,
    administrator: bool,
) -> dict[str, object]:
    login, display = _normalized_account(username, display_name)
    return {
        "username": login,
        "display_name": display,
        "password_hash": _hash_password(password),
        "roles": ["administrator"] if administrator else [],
        "enabled": True,
    }


def _read_password(args: argparse.Namespace) -> str:
    return _password_from_stdin() if args.password_stdin else _password_from_terminal(confirm=True)


def _accounts_init(args: argparse.Namespace) -> None:
    account = _account_payload(
        args.username,
        args.display_name,
        _read_password(args),
        administrator=True,
    )
    _write_private_json(
        args.file,
        {"format_version": 1, "accounts": [account]},
        create=True,
    )
    LocalAccountSettings(args.file)
    print(f"Initialized local accounts with administrator {account['username']}.")


def _accounts_add(args: argparse.Namespace) -> None:
    payload = _private_json(args.file)
    accounts = payload.get("accounts")
    if not isinstance(accounts, list):
        raise RuntimeError("Account file is invalid")
    account = _account_payload(
        args.username,
        args.display_name,
        _read_password(args),
        administrator=args.administrator,
    )
    if any(
        isinstance(value, dict)
        and str(value.get("username", "")).casefold() == account["username"]
        for value in accounts
    ):
        raise RuntimeError("That local username already exists")
    updated = {"format_version": 1, "accounts": [*accounts, account]}
    _write_private_json(args.file, updated, create=False)
    LocalAccountSettings(args.file)
    print(f"Added local account {account['username']}.")


def _accounts_password(args: argparse.Namespace) -> None:
    payload = _private_json(args.file)
    accounts = payload.get("accounts")
    if not isinstance(accounts, list):
        raise RuntimeError("Account file is invalid")
    username = args.username.strip().casefold()
    changed = False
    updated_accounts: list[object] = []
    password_hash = _hash_password(_read_password(args))
    for value in accounts:
        if isinstance(value, dict) and str(value.get("username", "")).casefold() == username:
            value = {**value, "password_hash": password_hash}
            changed = True
        updated_accounts.append(value)
    if not changed:
        raise RuntimeError("Local account was not found")
    _write_private_json(
        args.file,
        {"format_version": 1, "accounts": updated_accounts},
        create=False,
    )
    LocalAccountSettings(args.file)
    print(f"Rotated the password for {username}.")


def _accounts_list(args: argparse.Namespace) -> None:
    settings = LocalAccountSettings(args.file)
    for account in sorted(settings.accounts.values(), key=lambda value: value.username):
        role = "administrator" if "administrator" in account.roles else "reviewer"
        state = "enabled" if account.enabled else "disabled"
        print(f"{account.username}\t{role}\t{state}\t{account.display_name}")


def _storage_init(args: argparse.Namespace) -> None:
    storage = ManagedMatterStorage.initialize(args.root, policy=StoragePolicy.from_environment())
    print(f"Initialized managed storage {storage.root}.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recordbench")
    commands = parser.add_subparsers(dest="command", required=True)
    accounts = commands.add_parser("accounts", help="Manage local installation accounts")
    account_commands = accounts.add_subparsers(dest="accounts_command", required=True)
    for name, handler in (("init", _accounts_init), ("add", _accounts_add)):
        command = account_commands.add_parser(name)
        command.add_argument("--file", type=Path, required=True)
        command.add_argument("--username", required=True)
        command.add_argument("--display-name", required=True)
        command.add_argument("--password-stdin", action="store_true")
        if name == "add":
            command.add_argument("--administrator", action="store_true")
        command.set_defaults(handler=handler)
    password = account_commands.add_parser("password")
    password.add_argument("--file", type=Path, required=True)
    password.add_argument("--username", required=True)
    password.add_argument("--password-stdin", action="store_true")
    password.set_defaults(handler=_accounts_password)
    listing = account_commands.add_parser("list")
    listing.add_argument("--file", type=Path, required=True)
    listing.set_defaults(handler=_accounts_list)

    storage = commands.add_parser("storage", help="Initialize managed matter storage")
    storage_commands = storage.add_subparsers(dest="storage_command", required=True)
    initialize = storage_commands.add_parser("init")
    initialize.add_argument("--root", type=Path, required=True)
    initialize.set_defaults(handler=_storage_init)
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        parser.exit(1, f"recordbench: {exc}\n")


if __name__ == "__main__":
    main()
