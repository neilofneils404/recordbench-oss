"""Owner-authorized local account storage shared by operator and future UI code.

Readers need only read access. Writers require the existing private directory;
this module does not grant filesystem access or authorize browser requests.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterator, Mapping

from argon2 import PasswordHasher, extract_parameters

_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._@-]{2,127}$")
_REVISION = re.compile(r"^[0-9a-f]{64}$")
_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class LocalAccount:
    username: str
    display_name: str
    password_hash: str = field(repr=False)
    roles: frozenset[str] = frozenset()
    enabled: bool = True
    session_revision: str = field(default="legacy", repr=False)


@dataclass(frozen=True)
class LocalAccountChange:
    action: str
    username: str
    actor: str


def normalized_account(username: str, display_name: str) -> tuple[str, str]:
    login = (username or "").strip().casefold()
    display = (display_name or "").strip()
    if _USERNAME.fullmatch(login) is None:
        raise RuntimeError("Username must be 3-128 lowercase letters, numbers, dots, dashes, underscores, or @")
    if not display or len(display) > 160 or any(ord(value) < 32 for value in display):
        raise RuntimeError("Display name is missing or invalid")
    return login, display


def hash_password(value: str) -> str:
    if not isinstance(value, str) or not 14 <= len(value) <= 1024 or "\x00" in value:
        raise RuntimeError("Local account passwords must contain 14 to 1,024 characters without NUL")
    return PasswordHasher().hash(value)


def _parse(payload: object) -> tuple[int, dict[str, LocalAccount]]:
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
        try:
            parameters = extract_parameters(password_hash)
        except Exception as exc:
            raise RuntimeError("Local account file contains an invalid password hash") from exc
        if parameters.type.name.casefold() != "id":
            raise RuntimeError("Local account passwords must use Argon2id")
        accounts[username] = LocalAccount(username, display, password_hash, frozenset(roles), enabled, revision)
    if not any(account.enabled and "administrator" in account.roles for account in accounts.values()):
        raise RuntimeError("At least one enabled local administrator is required")
    return version, accounts


def _payload(accounts: Mapping[str, LocalAccount]) -> dict[str, object]:
    return {"format_version": 2, "accounts": [
        {"username": account.username, "display_name": account.display_name,
         "password_hash": account.password_hash, "roles": sorted(account.roles),
         "enabled": account.enabled, "session_revision": account.session_revision}
        for account in accounts.values()
    ]}


@contextmanager
def _parent(path: Path, *, create: bool = False) -> Iterator[int]:
    if not path.is_absolute() or path.name in {"", ".", ".."} or ".." in path.parts:
        raise RuntimeError("Account file must be an exact absolute path")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parent.parts[1:]:
            try:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise RuntimeError("Account directory must be owned by the service account and not writable by other users")
        yield descriptor
    finally:
        os.close(descriptor)


def _private_metadata(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise RuntimeError("Local account file is unavailable or unsafe")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise RuntimeError("Local account file must have mode 0600")
    if metadata.st_size > _MAX_BYTES:
        raise RuntimeError("Local account file exceeds its size limit")


def _read(directory: int, name: str) -> tuple[bytes, int, dict[str, LocalAccount]]:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        _private_metadata(descriptor)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(_MAX_BYTES + 1)
        if len(data) > _MAX_BYTES:
            raise RuntimeError("Local account file exceeds its size limit")
        try:
            version, accounts = _parse(json.loads(data.decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("Local account file is unreadable or invalid") from exc
        return data, version, accounts
    finally:
        os.close(descriptor)


def _write(directory: int, name: str, data: bytes, *, create: bool = False) -> None:
    temporary = f".{name}-{secrets.token_hex(16)}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if create:
            # A concurrent initializer/backup cannot replace an existing file.
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        else:
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


class LocalAccountRepository:
    """Fresh snapshots and process-serialized mutations of the existing account file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def read(self) -> dict[str, LocalAccount]:
        with _parent(self.path) as directory:
            return _read(directory, self.path.name)[2]

    @contextmanager
    def _writer(self, *, create: bool = False) -> Iterator[int]:
        with _parent(self.path, create=create) as directory:
            lock = os.open(f".{self.path.name}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                           0o600, dir_fd=directory)
            try:
                _private_metadata(lock)
                fcntl.flock(lock, fcntl.LOCK_EX)
                yield directory
            finally:
                os.close(lock)

    @staticmethod
    def _receipt(action: str, username: str, actor: str) -> LocalAccountChange:
        if not isinstance(actor, str) or not actor or len(actor) > 200 or any(ord(char) < 32 for char in actor):
            raise RuntimeError("Account change attribution is required")
        return LocalAccountChange(action, username, actor)

    def _change(self, action: str, username: str, actor: str,
                update: Callable[[dict[str, LocalAccount]], None]) -> LocalAccountChange:
        receipt = self._receipt(action, username, actor)
        with self._writer() as directory:
            _, version, accounts = _read(directory, self.path.name)
            if version != 2:
                raise RuntimeError("Migrate local accounts with an explicit backup before changing them: run recordbench accounts migrate with --file and a new --backup-file")
            update(accounts)
            payload = _payload(accounts)
            _parse(payload)  # Last-admin and size/shape checks share the writer lock.
            data = (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode()
            if len(data) > _MAX_BYTES:
                raise RuntimeError("Local account file exceeds its size limit")
            _write(directory, self.path.name, data)
        return receipt

    def initialize(self, username: str, display_name: str, password: str, *, actor: str) -> LocalAccountChange:
        username, display_name = normalized_account(username, display_name)
        receipt = self._receipt("initialize", username, actor)
        account = LocalAccount(username, display_name, hash_password(password), frozenset({"administrator"}), True, secrets.token_hex(32))
        data = (json.dumps(_payload({username: account}), indent=2, sort_keys=True) + "\n").encode()
        with self._writer(create=True) as directory:
            _write(directory, self.path.name, data, create=True)
        return receipt

    def migrate(self, backup_file: Path, *, actor: str) -> LocalAccountChange:
        receipt = self._receipt("migrate", "*", actor)
        backup_file = Path(backup_file)
        if backup_file == self.path:
            raise RuntimeError("Migration backup must be separate from the account file")
        with self._writer() as directory:
            data, version, accounts = _read(directory, self.path.name)
            if version != 1:
                raise RuntimeError("Local accounts are already in the current format")
            with _parent(backup_file, create=True) as backup_directory:
                _write(backup_directory, backup_file.name, data, create=True)
                restored_data, restored_version, restored_accounts = _read(backup_directory, backup_file.name)
                if restored_data != data or restored_version != version or restored_accounts != accounts:
                    raise RuntimeError("Migration backup verification failed")
            updated = {name: replace(account, session_revision=secrets.token_hex(32)) for name, account in accounts.items()}
            payload = _payload(updated)
            _parse(payload)
            encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
            if len(encoded) > _MAX_BYTES:
                raise RuntimeError("Migrated local account file exceeds its size limit")
            _write(directory, self.path.name, encoded)
        return receipt

    def create(self, username: str, display_name: str, password: str, *, administrator: bool = False,
               actor: str) -> LocalAccountChange:
        username, display_name = normalized_account(username, display_name)
        if not isinstance(administrator, bool):
            raise RuntimeError("Administrator role must be enabled or disabled")
        account = LocalAccount(username, display_name, hash_password(password),
                               frozenset({"administrator"}) if administrator else frozenset(), True, secrets.token_hex(32))
        def update(accounts: dict[str, LocalAccount]) -> None:
            if username in accounts:
                raise RuntimeError("That local username already exists")
            accounts[username] = account
        return self._change("create", username, actor, update)

    def _update(self, action: str, username: str, actor: str, **changes: object) -> LocalAccountChange:
        username = (username or "").strip().casefold()
        def update(accounts: dict[str, LocalAccount]) -> None:
            if username not in accounts:
                raise RuntimeError("Local account was not found")
            old = accounts[username]
            if action != "display-name":
                changes["session_revision"] = secrets.token_hex(32)
            accounts[username] = replace(old, **changes)
        return self._change(action, username, actor, update)

    def change_display_name(self, username: str, display_name: str, *, actor: str) -> LocalAccountChange:
        username, display_name = normalized_account(username, display_name)
        return self._update("display-name", username, actor, display_name=display_name)

    def change_password(self, username: str, password: str, *, actor: str) -> LocalAccountChange:
        return self._update("password", username, actor, password_hash=hash_password(password))

    def set_enabled(self, username: str, enabled: bool, *, actor: str) -> LocalAccountChange:
        if not isinstance(enabled, bool):
            raise RuntimeError("Account state must be enabled or disabled")
        return self._update("enable" if enabled else "disable", username, actor, enabled=enabled)

    def set_administrator(self, username: str, administrator: bool, *, actor: str) -> LocalAccountChange:
        if not isinstance(administrator, bool):
            raise RuntimeError("Administrator role must be enabled or disabled")
        return self._update("administrator" if administrator else "reviewer", username, actor,
                            roles=frozenset({"administrator"}) if administrator else frozenset())
