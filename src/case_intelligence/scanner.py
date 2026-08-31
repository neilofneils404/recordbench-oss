from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .contracts import validate_relative_path
from .fixture_builder import _FILE_READ_FLAGS, _open_directory_path, _openat2_beneath


@dataclass(frozen=True)
class ScanLimits:
    max_files: int = 64
    max_depth: int = 8
    max_file_bytes: int = 2 * 1024 * 1024
    max_aggregate_bytes: int = 8 * 1024 * 1024
    max_path_bytes: int = 1024


@dataclass(frozen=True)
class ScannedFile:
    relative_path: str
    display_name: str
    media_type: str
    byte_size: int
    sha256: str
    stable_device: int
    stable_inode: int
    stable_mtime_ns: int
    content: bytes


class ScanError(ValueError):
    pass


_MEDIA = {".txt": "text/plain", ".svg": "image/svg+xml", ".wav": "audio/wav"}


class SyntheticScanner:
    """Bounded Linux scanner permanently bound to one caller-owned root."""

    def __init__(
        self,
        root: Path,
        *,
        limits: ScanLimits = ScanLimits(),
        _test_hook: Callable[[str, str], None] | None = None,
    ) -> None:
        absolute = Path(os.path.abspath(root))
        if absolute == Path("/mnt") or Path("/mnt") in absolute.parents:
            raise ScanError("/mnt roots are prohibited")
        self.root = absolute
        self.limits = limits
        self._test_hook = _test_hook

    def scan(self) -> tuple[ScannedFile, ...]:
        _, root_fd = _open_directory_path(self.root, label="synthetic scanner root")
        try:
            paths: list[str] = []
            self._enumerate(root_fd, "", 0, paths)
            paths.sort(key=lambda value: value.encode("utf-8"))
            if len(paths) > self.limits.max_files:
                raise ScanError("maximum file count exceeded")
            keys: set[tuple[str, ...]] = set()
            output: list[ScannedFile] = []
            aggregate = 0
            for relative_path in paths:
                key = tuple(part.rstrip(" .").casefold() for part in relative_path.split("/"))
                if key in keys:
                    raise ScanError("Windows-equivalent path collision")
                keys.add(key)
                item = self._read(root_fd, relative_path)
                aggregate += item.byte_size
                if aggregate > self.limits.max_aggregate_bytes:
                    raise ScanError("maximum aggregate bytes exceeded")
                output.append(item)
            return tuple(output)
        finally:
            os.close(root_fd)

    def _enumerate(self, directory_fd: int, prefix: str, depth: int, paths: list[str]) -> None:
        if depth > self.limits.max_depth:
            raise ScanError("maximum depth exceeded")
        try:
            entries = sorted(os.scandir(directory_fd), key=lambda item: os.fsencode(item.name))
        except OSError as exc:
            raise ScanError("directory enumeration failed") from exc
        for entry in entries:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            try:
                validate_relative_path(relative)
            except ValueError as exc:
                raise ScanError("unsafe relative path") from exc
            if len(relative.encode("utf-8")) > self.limits.max_path_bytes:
                raise ScanError("maximum path bytes exceeded")
            if entry.is_symlink():
                raise ScanError("symlink entries are prohibited")
            if entry.is_dir(follow_symlinks=False):
                child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=directory_fd)
                try:
                    self._enumerate(child, relative, depth + 1, paths)
                finally:
                    os.close(child)
            elif entry.is_file(follow_symlinks=False):
                paths.append(relative)
            else:
                raise ScanError("non-regular entries are prohibited")

    def _read(self, root_fd: int, relative_path: str) -> ScannedFile:
        if self._test_hook:
            self._test_hook("before_open", relative_path)
        try:
            fd = _openat2_beneath(root_fd, relative_path, _FILE_READ_FLAGS)
        except (OSError, RuntimeError) as exc:
            raise ScanError("final file resolution failed") from exc
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise ScanError("source is not regular")
            if before.st_size > self.limits.max_file_bytes:
                raise ScanError("maximum file bytes exceeded")
            chunks: list[bytes] = []
            remaining = self.limits.max_file_bytes + 1
            while remaining and (chunk := os.read(fd, min(1024 * 1024, remaining))):
                chunks.append(chunk)
                remaining -= len(chunk)
                if self._test_hook:
                    self._test_hook("hash_chunk", relative_path)
            content = b"".join(chunks)
            if len(content) > self.limits.max_file_bytes:
                raise ScanError("maximum file bytes exceeded")
            after = os.fstat(fd)
            identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            if identity_before != identity_after or len(content) != before.st_size:
                raise ScanError("file mutated during stable read")
            suffix = Path(relative_path).suffix.casefold()
            return ScannedFile(
                relative_path=relative_path,
                display_name=Path(relative_path).name,
                media_type=_MEDIA.get(suffix, "application/octet-stream"),
                byte_size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                stable_device=before.st_dev,
                stable_inode=before.st_ino,
                stable_mtime_ns=before.st_mtime_ns,
                content=content,
            )
        finally:
            os.close(fd)
