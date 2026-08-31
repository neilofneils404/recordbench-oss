from __future__ import annotations

import ctypes
import errno
import json
import os
import platform
import stat
import sys
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from case_intelligence.contracts import validate_relative_path


@dataclass(frozen=True)
class FixtureBuildResult:
    """Result of constructing one validated synthetic fixture tree."""

    root: Path
    manifest: dict[str, Any]
    file_count: int


_TestHook = Callable[[str, str], None]
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
_FILE_READ_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW
_FILE_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
_RESOLVE_NO_SYMLINKS = 0x04
_RESOLVE_BENEATH = 0x08
_OPENAT2_RESOLVE_FLAGS = _RESOLVE_BENEATH | _RESOLVE_NO_SYMLINKS
_OPENAT2_SYSCALLS = {
    "aarch64": 437,
    "armv7l": 437,
    "ppc64le": 437,
    "riscv64": 437,
    "s390x": 437,
    "x86_64": 437,
}


class _OpenHow(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    ]


def _openat2_beneath(
    root_descriptor: int,
    relative_path: str,
    flags: int,
    *,
    mode: int = 0,
) -> int:
    """Atomically resolve a no-symlink path beneath a held Linux root."""

    if sys.platform != "linux":
        raise RuntimeError("fixture builder requires Linux openat2 containment")
    syscall_number = _OPENAT2_SYSCALLS.get(platform.machine().lower())
    if syscall_number is None:
        raise RuntimeError(
            f"fixture builder does not support openat2 on architecture {platform.machine()!r}"
        )
    encoded_path = os.fsencode(relative_path)
    how = _OpenHow(flags=flags, mode=mode, resolve=_OPENAT2_RESOLVE_FLAGS)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    result = libc.syscall(
        ctypes.c_long(syscall_number),
        ctypes.c_int(root_descriptor),
        ctypes.c_char_p(encoded_path),
        ctypes.byref(how),
        ctypes.c_size_t(ctypes.sizeof(how)),
    )
    if result < 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.ENOSYS, errno.E2BIG, errno.EINVAL}:
            raise RuntimeError("fixture builder requires kernel support for Linux openat2")
        raise OSError(error_number, os.strerror(error_number), relative_path)
    return int(result)


def _open_directory_path(path: Path, *, label: str) -> tuple[Path, int]:
    """Open every absolute path component without following symlinks."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    descriptor = os.open("/", _DIRECTORY_FLAGS)
    try:
        for component in absolute.parts[1:]:
            try:
                child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except OSError as exc:
                if exc.errno == errno.ENOENT:
                    message = f"{label} must already exist"
                else:
                    message = f"{label} ancestry cannot contain a symlink and must be directories"
                raise ValueError(message) from exc
            os.close(descriptor)
            descriptor = child
        return absolute, descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _fd_identity(descriptor: int) -> tuple[int, int]:
    details = os.fstat(descriptor)
    return details.st_dev, details.st_ino


def _fd_is_within(candidate: int, ancestor: int) -> bool:
    """Compare already-open directory capabilities, including ancestry."""

    ancestor_identity = _fd_identity(ancestor)
    current = os.dup(candidate)
    try:
        while True:
            current_identity = _fd_identity(current)
            if current_identity == ancestor_identity:
                return True
            parent = os.open("..", _DIRECTORY_FLAGS, dir_fd=current)
            parent_identity = _fd_identity(parent)
            if parent_identity == current_identity:
                os.close(parent)
                return False
            os.close(current)
            current = parent
    finally:
        os.close(current)


def _manifest_records(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    try:
        matters = manifest["matters"]
        records = [
            record
            for matter in matters
            for source in matter["sources"]
            for record in (source, source["representation"])
        ]
    except (KeyError, TypeError) as exc:
        raise ValueError("fixture manifest has an invalid source structure") from exc
    if not isinstance(matters, list) or not all(isinstance(record, Mapping) for record in records):
        raise ValueError("fixture manifest has an invalid source structure")
    return records


def _destination_key(relative_path: str) -> tuple[str, ...]:
    validated = validate_relative_path(relative_path)
    return tuple(component.rstrip(" .").casefold() for component in validated.split("/"))


def _validate_synthetic_manifest(manifest: Mapping[str, Any]) -> None:
    if (
        manifest.get("provenance") != "synthetic"
        or manifest.get("confidential_data") is not False
        or manifest.get("requires_model") is not False
        or manifest.get("requires_network") is not False
    ):
        raise ValueError("fixture builder accepts synthetic local manifests only")


def _walk_directory(
    root_descriptor: int,
    components: list[str],
    *,
    create: bool,
    label: str,
) -> int:
    descriptor = os.dup(root_descriptor)
    try:
        for component in components:
            if create:
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            try:
                child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except OSError as exc:
                raise ValueError(
                    f"{label} component must be a non-symlink directory beneath its root"
                ) from exc
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_source_file(
    root_descriptor: int,
    relative_path: str,
    *,
    test_hook: _TestHook | None,
) -> int:
    parts = relative_path.split("/")
    parent = _walk_directory(
        root_descriptor,
        parts[:-1],
        create=False,
        label="fixture source path",
    )
    try:
        if test_hook is not None:
            test_hook("source_parent", relative_path)
        if not _fd_is_within(parent, root_descriptor):
            raise ValueError("fixture source path parent no longer remains beneath its root")
        try:
            descriptor = _openat2_beneath(
                root_descriptor,
                relative_path,
                _FILE_READ_FLAGS,
            )
        except OSError as exc:
            message = (
                "fixture source path cannot be a symlink and must remain beneath its root"
            )
            raise ValueError(message) from exc
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError("fixture source path must be a regular file")
        return descriptor
    finally:
        os.close(parent)


def _read_bytes(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def _read_manifest(source_descriptor: int) -> tuple[dict[str, Any], bytes]:
    descriptor = _open_source_file(source_descriptor, "manifest.json", test_hook=None)
    try:
        payload = _read_bytes(descriptor)
    finally:
        os.close(descriptor)
    try:
        parsed = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("fixture manifest must be valid UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("fixture manifest must be a JSON object")
    return parsed, payload


def _open_destination_file(
    root_descriptor: int,
    relative_path: str,
    *,
    test_hook: _TestHook | None,
) -> int:
    parts = relative_path.split("/")
    parent = _walk_directory(
        root_descriptor,
        parts[:-1],
        create=True,
        label="fixture target path",
    )
    try:
        if test_hook is not None:
            test_hook("destination_parent", relative_path)
        if not _fd_is_within(parent, root_descriptor):
            raise ValueError("fixture target path parent no longer remains beneath its root")
        try:
            return _openat2_beneath(
                root_descriptor,
                relative_path,
                _FILE_WRITE_FLAGS,
                mode=0o600,
            )
        except OSError as exc:
            raise ValueError(
                "fixture target path must remain a non-symlink destination beneath its root"
            ) from exc
    finally:
        os.close(parent)


def _copy_file(source_descriptor: int, target_descriptor: int) -> None:
    while chunk := os.read(source_descriptor, 1024 * 1024):
        view = memoryview(chunk)
        while view:
            written = os.write(target_descriptor, view)
            view = view[written:]


def build_fixture(
    source_root: Path,
    target_root: Path,
    *,
    manifest: Mapping[str, Any] | None = None,
    _test_hook: _TestHook | None = None,
) -> FixtureBuildResult:
    """Copy a validated synthetic fixture into an empty caller-owned directory.

    On Linux, trusted roots and every descendant are traversed through directory
    file descriptors with no-follow checks. Final source and destination opens
    are resolved atomically from the held roots with ``openat2`` beneath/no-
    symlink constraints. Source files are opened and verified before destination
    creation. ``_test_hook`` exists only for deterministic race regression tests.
    """

    source_path, source_descriptor = _open_directory_path(
        Path(source_root), label="fixture source root"
    )
    target_path, target_descriptor = _open_directory_path(
        Path(target_root), label="fixture target root"
    )
    with ExitStack() as resources:
        resources.callback(os.close, source_descriptor)
        resources.callback(os.close, target_descriptor)

        if _fd_is_within(source_descriptor, target_descriptor) or _fd_is_within(
            target_descriptor, source_descriptor
        ):
            raise ValueError("fixture source and target roots must not overlap")
        if os.listdir(target_descriptor):
            raise ValueError("fixture target root must be empty")

        if manifest is None:
            loaded_manifest, manifest_bytes = _read_manifest(source_descriptor)
        else:
            loaded_manifest = dict(manifest)
            manifest_bytes = (
                json.dumps(loaded_manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            ).encode("utf-8")

        _validate_synthetic_manifest(loaded_manifest)
        records = _manifest_records(loaded_manifest)
        planned: list[str] = []
        destination_keys: set[tuple[str, ...]] = {_destination_key("manifest.json")}

        for record in records:
            relative_value = record.get("path")
            if not isinstance(relative_value, str):
                raise ValueError("fixture source path must be a string")
            relative_path = validate_relative_path(relative_value)
            destination_key = _destination_key(relative_path)
            if destination_key in destination_keys:
                raise ValueError("duplicate or ambiguous fixture destination")
            destination_keys.add(destination_key)
            planned.append(relative_path)

        opened_sources: list[tuple[str, int]] = []
        for relative_path in planned:
            descriptor = _open_source_file(
                source_descriptor,
                relative_path,
                test_hook=_test_hook,
            )
            resources.callback(os.close, descriptor)
            opened_sources.append((relative_path, descriptor))

        for relative_path, source_file in opened_sources:
            target_file = _open_destination_file(
                target_descriptor,
                relative_path,
                test_hook=_test_hook,
            )
            try:
                _copy_file(source_file, target_file)
            finally:
                os.close(target_file)

        manifest_target = _open_destination_file(
            target_descriptor,
            "manifest.json",
            test_hook=_test_hook,
        )
        try:
            view = memoryview(manifest_bytes)
            while view:
                written = os.write(manifest_target, view)
                view = view[written:]
        finally:
            os.close(manifest_target)

    result_manifest = dict(loaded_manifest)
    result_manifest["verified_file_count"] = len(planned)
    return FixtureBuildResult(
        root=target_path,
        manifest=result_manifest,
        file_count=len(planned),
    )
