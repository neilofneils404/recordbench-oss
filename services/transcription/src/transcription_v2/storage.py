"""Filesystem storage primitives for transcription v2.

Uploads are consumed incrementally, hashed while being written, and installed
atomically beneath a validated per-job directory.  This module does not log
filenames or content.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_REPEATED_UNDERSCORE_RE = re.compile(r"_+")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class StorageError(RuntimeError):
    """Base exception for v2 file storage."""


class InvalidStoragePathError(StorageError):
    """A path or identifier would escape its assigned storage boundary."""


class FileTooLargeError(StorageError):
    """A streamed upload exceeded its configured byte limit."""


class ContentCollisionError(StorageError):
    """An existing content-addressed path does not match its digest."""


@dataclass(frozen=True, slots=True)
class JobPaths:
    root: Path
    input: Path
    work: Path
    output: Path


@dataclass(frozen=True, slots=True)
class IngestedFile:
    original_name: str
    safe_name: str
    relative_path: str
    absolute_path: Path
    size_bytes: int
    sha256: str
    media_type: str | None


def validate_job_id(job_id: str) -> str:
    if not isinstance(job_id, str) or not _IDENTIFIER_RE.fullmatch(job_id):
        raise InvalidStoragePathError(
            "job_id must be 1-64 ASCII letters, numbers, underscores, or hyphens"
        )
    return job_id


def sanitize_filename(
    name: str,
    *,
    fallback: str = "upload.bin",
    max_length: int = 160,
) -> str:
    """Return a basename safe for local paths and archive members.

    The original filename can be retained as metadata, but only this normalized
    ASCII form should be used on disk.  Both POSIX and Windows separators are
    treated as untrusted path separators.
    """

    if max_length < 16:
        raise ValueError("max_length must be at least 16")
    raw = unicodedata.normalize("NFKC", str(name or ""))
    raw = raw.replace("\\", "/").split("/")[-1].replace("\x00", "")
    cleaned = _SAFE_NAME_RE.sub("_", raw)
    cleaned = _REPEATED_UNDERSCORE_RE.sub("_", cleaned).strip(" ._")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = _SAFE_NAME_RE.sub("_", fallback).strip(" ._") or "upload.bin"

    # Preserve a short extension when truncating long names.
    suffix = Path(cleaned).suffix
    if len(suffix) > 20:
        suffix = ""
    if len(cleaned) > max_length:
        stem_budget = max_length - len(suffix)
        stem = cleaned[:stem_budget].rstrip(" ._") or "upload"
        cleaned = stem + suffix

    # Avoid a hidden or option-like path even after normalization.
    cleaned = cleaned.lstrip(".-") or "upload.bin"
    return cleaned


def display_filename(name: str, *, max_length: int = 255) -> str:
    """Return bounded, path-free Unicode metadata suitable for the staff UI."""

    if max_length < 16:
        raise ValueError("max_length must be at least 16")
    value = unicodedata.normalize("NFKC", str(name or ""))
    value = value.replace("\\", "/").split("/")[-1]
    value = _CONTROL_RE.sub("_", value).strip()
    if not value or value in {".", ".."}:
        value = "upload.bin"
    return value[:max_length]


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _hash_file(path: Path, chunk_size: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


class FileStorage:
    """Content-addressed, per-job filesystem storage."""

    def __init__(self, root: str | os.PathLike[str], *, chunk_size: int = 1024 * 1024):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        root_path = Path(root).expanduser()
        root_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = root_path.resolve()
        self.jobs_root = self.root / "jobs"
        self.jobs_root.mkdir(mode=0o700, exist_ok=True)
        if self.jobs_root.is_symlink() or self.jobs_root.resolve().parent != self.root:
            raise InvalidStoragePathError("jobs directory must be a real child of storage root")
        self.chunk_size = int(chunk_size)

    def job_paths(self, job_id: str, *, create: bool = True) -> JobPaths:
        job_id = validate_job_id(job_id)
        job_root = self.jobs_root / job_id
        if create:
            job_root.mkdir(mode=0o700, exist_ok=True)
        if job_root.is_symlink():
            raise InvalidStoragePathError("job directory cannot be a symlink")
        resolved_job_root = job_root.resolve()
        if not _is_relative_to(resolved_job_root, self.jobs_root.resolve()):
            raise InvalidStoragePathError("job directory escapes storage root")

        children: list[Path] = []
        for name in ("input", "work", "output"):
            path = resolved_job_root / name
            if create:
                path.mkdir(mode=0o700, exist_ok=True)
            if path.is_symlink():
                raise InvalidStoragePathError(f"job {name} directory cannot be a symlink")
            resolved = path.resolve()
            if not _is_relative_to(resolved, resolved_job_root):
                raise InvalidStoragePathError(f"job {name} directory escapes job boundary")
            children.append(resolved)
        return JobPaths(
            root=resolved_job_root,
            input=children[0],
            work=children[1],
            output=children[2],
        )

    def ingest_stream(
        self,
        job_id: str,
        source: BinaryIO,
        original_name: str,
        *,
        media_type: str | None = None,
        max_bytes: int | None = None,
    ) -> IngestedFile:
        """Stream an upload to durable storage and return its SHA-256 identity."""

        if max_bytes is not None and max_bytes < 0:
            raise ValueError("max_bytes cannot be negative")
        paths = self.job_paths(job_id)
        safe_name = sanitize_filename(original_name)
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=".upload-", suffix=".part", dir=paths.input
        )
        temp_path = Path(temp_name)
        digest = hashlib.sha256()
        size = 0

        try:
            with os.fdopen(temp_fd, "wb") as destination:
                os.chmod(temp_path, 0o600)
                while True:
                    chunk = source.read(self.chunk_size)
                    if chunk == b"":
                        break
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise TypeError("binary upload streams must return bytes")
                    chunk_size = len(chunk)
                    if chunk_size == 0:
                        continue
                    size += chunk_size
                    if max_bytes is not None and size > max_bytes:
                        raise FileTooLargeError(
                            f"upload exceeds configured limit of {max_bytes} bytes"
                        )
                    destination.write(chunk)
                    digest.update(chunk)
                destination.flush()
                os.fsync(destination.fileno())

            sha256 = digest.hexdigest()
            final_path = paths.input / f"{sha256}--{safe_name}"
            try:
                # A same-directory hard link is an atomic no-overwrite install.
                os.link(temp_path, final_path)
            except FileExistsError:
                existing_size, existing_hash = _hash_file(final_path, self.chunk_size)
                if existing_size != size or existing_hash != sha256:
                    raise ContentCollisionError(
                        "existing content-addressed file does not match its digest"
                    )
            # The upload is immutable after its content identity is recorded.
            # Worker and signed-review delivery need read access only.
            os.chmod(final_path, 0o400)
            temp_path.unlink(missing_ok=True)
            _fsync_directory(paths.input)
            relative_path = final_path.relative_to(self.root).as_posix()
            return IngestedFile(
                original_name=display_filename(original_name),
                safe_name=safe_name,
                relative_path=relative_path,
                absolute_path=final_path,
                size_bytes=size,
                sha256=sha256,
                media_type=media_type,
            )
        except BaseException:
            # Includes cancellation/KeyboardInterrupt: partial media must not linger.
            temp_path.unlink(missing_ok=True)
            raise

    def resolve_relative(self, relative_path: str, *, must_exist: bool = True) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
            raise InvalidStoragePathError("storage path must be normalized and relative")
        resolved = (self.root / candidate).resolve(strict=must_exist)
        if not _is_relative_to(resolved, self.root):
            raise InvalidStoragePathError("path escapes storage root")
        return resolved

    def open_input(self, job_id: str, relative_path: str) -> BinaryIO:
        paths = self.job_paths(job_id, create=False)
        resolved = self.resolve_relative(relative_path)
        if not _is_relative_to(resolved, paths.input.resolve()):
            raise InvalidStoragePathError("path is not an input for this job")
        return resolved.open("rb")

    def output_path(self, job_id: str, filename: str) -> Path:
        paths = self.job_paths(job_id)
        return paths.output / sanitize_filename(filename, fallback="output.bin")

    def delete_job_inputs(self, job_id: str) -> bool:
        """Delete source uploads while retaining work/output delivery files."""

        paths = self.job_paths(job_id, create=False)
        input_path = paths.input
        if not input_path.exists():
            return False
        resolved = input_path.resolve()
        if not _is_relative_to(resolved, paths.root):
            raise InvalidStoragePathError("input directory escapes its job boundary")
        if input_path.is_symlink():
            raise InvalidStoragePathError("refusing to follow a symlinked input directory")
        shutil.rmtree(input_path)
        _fsync_directory(paths.root)
        return True

    def delete_job_tree(self, job_id: str) -> bool:
        """Hard-delete one validated per-job tree without following symlinks."""

        job_id = validate_job_id(job_id)
        candidate = self.jobs_root / job_id
        if not candidate.exists() and not candidate.is_symlink():
            return False
        if candidate.is_symlink():
            raise InvalidStoragePathError("refusing to follow a symlinked job directory")
        resolved = candidate.resolve()
        if resolved.parent != self.jobs_root.resolve():
            raise InvalidStoragePathError("job directory escapes storage root")
        shutil.rmtree(resolved)
        _fsync_directory(self.jobs_root)
        return True

    def iter_file(
        self, relative_path: str, *, chunk_size: int | None = None
    ) -> Iterator[bytes]:
        read_size = self.chunk_size if chunk_size is None else int(chunk_size)
        if read_size <= 0:
            raise ValueError("chunk_size must be positive")
        path = self.resolve_relative(relative_path)
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(read_size)
                if not chunk:
                    return
                yield chunk
