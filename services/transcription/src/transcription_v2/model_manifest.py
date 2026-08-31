"""Offline approval-manifest verification for local inference artifacts.

The verifier deliberately has no model-runtime dependencies.  Paths in the
manifest are opened relative to an already-open model-cache directory with
``O_NOFOLLOW`` so a symlink cannot redirect verification outside the approved
cache.  Public reports contain model metadata and aggregate counts, never local
filesystem paths or file contents.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


MODEL_MANIFEST_SCHEMA = "transcription-v2-model-manifest-v1"
DEFAULT_MODEL_MANIFEST_NAME = "approved-model-manifest.json"
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_ARTIFACTS = 128
_MAX_FILES = 4096
_HASH_CHUNK_BYTES = 1024 * 1024
_ROLE_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
_FLOATING_REVISIONS = {"head", "latest", "main", "master"}
_FileSignature = tuple[int, int, int, int, int]


_PUBLIC_MESSAGES = {
    "cache_missing": "The approved model cache is unavailable.",
    "cache_not_directory": "The approved model cache is invalid.",
    "cache_symlink": "The approved model cache must not be a symbolic link.",
    "manifest_outside_cache": "The model manifest must stay inside the approved cache.",
    "manifest_missing": "The approved model manifest is missing.",
    "manifest_symlink": "The approved model manifest must not use symbolic links.",
    "manifest_unreadable": "The approved model manifest cannot be read safely.",
    "manifest_too_large": "The approved model manifest exceeds its size limit.",
    "manifest_invalid_json": "The approved model manifest is not valid JSON.",
    "manifest_invalid": "The approved model manifest does not match the required schema.",
    "manifest_schema_unsupported": "The approved model manifest schema is unsupported.",
    "artifact_missing": "An approved model artifact is missing.",
    "artifact_symlink": "Approved model artifacts must not use symbolic links.",
    "artifact_not_regular": "An approved model artifact is not a regular file.",
    "artifact_unreadable": "An approved model artifact cannot be read safely.",
    "artifact_size_mismatch": "An approved model artifact has an unexpected size.",
    "artifact_sha256_mismatch": "An approved model artifact failed SHA-256 verification.",
    "artifact_changed": "An approved model artifact changed during verification.",
}


class ModelManifestError(RuntimeError):
    """A privacy-safe, stable failure from manifest verification."""

    def __init__(
        self,
        code: str,
        *,
        artifact_role: str | None = None,
        file_index: int | None = None,
    ) -> None:
        self.code = code
        self.public_message = _PUBLIC_MESSAGES.get(
            code, "The approved model artifacts could not be verified."
        )
        self.artifact_role = artifact_role
        self.file_index = file_index
        super().__init__(self.public_message)

    def public_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "status": "not_ready",
            "ready": False,
            "required": True,
            "code": self.code,
            "message": self.public_message,
        }
        if self.artifact_role is not None:
            value["artifact_role"] = self.artifact_role
        if self.file_index is not None:
            value["file_index"] = self.file_index
        return value


@dataclass(frozen=True, slots=True)
class ArtifactReadiness:
    role: str
    model_id: str
    revision: str
    license: str
    file_count: int
    verified_bytes: int
    verified_file_signatures: frozenset[_FileSignature] = field(
        default_factory=frozenset,
        repr=False,
        compare=False,
    )

    def public_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "model_id": self.model_id,
            "revision": self.revision,
            "license": self.license,
            "file_count": self.file_count,
            "verified_bytes": self.verified_bytes,
        }


@dataclass(frozen=True, slots=True)
class ModelReadiness:
    schema_version: str
    manifest_sha256: str
    artifacts: tuple[ArtifactReadiness, ...]
    verified_file_count: int
    verified_bytes: int

    def authorizes_file(
        self,
        path: str | Path,
        *,
        role: str,
        model_id: str,
    ) -> bool:
        """Return whether an exact verified artifact file backs ``path``.

        ``os.stat`` follows the snapshot symlink used by the Hugging Face cache,
        allowing a manifest to approve the regular blob while the model loader
        receives ``snapshots/<revision>/config.yaml``. File identities remain
        private and are intentionally omitted from :meth:`public_dict`.
        """

        try:
            status = os.stat(Path(path).expanduser())
        except OSError:
            return False
        if not stat.S_ISREG(status.st_mode):
            return False
        signature = _file_signature(status)
        return any(
            artifact.role == role
            and artifact.model_id == model_id
            and signature in artifact.verified_file_signatures
            for artifact in self.artifacts
        )

    def public_dict(self) -> dict[str, object]:
        return {
            "status": "ready",
            "ready": True,
            "required": True,
            "schema_version": self.schema_version,
            "manifest_sha256": self.manifest_sha256,
            "artifact_count": len(self.artifacts),
            "verified_file_count": self.verified_file_count,
            "verified_bytes": self.verified_bytes,
            "artifacts": [artifact.public_dict() for artifact in self.artifacts],
        }


@dataclass(frozen=True, slots=True)
class _ExpectedFile:
    parts: tuple[str, ...]
    size_bytes: int
    sha256: str
    artifact_role: str
    file_index: int


@dataclass(frozen=True, slots=True)
class _Artifact:
    role: str
    model_id: str
    revision: str
    license: str
    files: tuple[_ExpectedFile, ...]


class _DuplicateKeyError(ValueError):
    pass


def _object_without_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKeyError
        value[key] = item
    return value


def _absolute_path(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _cache_root(path: str | Path) -> tuple[Path, int]:
    root = _absolute_path(path)
    try:
        root_status = os.lstat(root)
    except FileNotFoundError:
        raise ModelManifestError("cache_missing") from None
    except OSError:
        raise ModelManifestError("cache_not_directory") from None
    if stat.S_ISLNK(root_status.st_mode):
        raise ModelManifestError("cache_symlink")
    if not stat.S_ISDIR(root_status.st_mode):
        raise ModelManifestError("cache_not_directory")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(root, flags)
    except OSError:
        raise ModelManifestError("cache_not_directory") from None
    return root, descriptor


def _relative_parts(root: Path, path: str | Path) -> tuple[str, ...]:
    candidate = _absolute_path(path)
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise ModelManifestError("manifest_outside_cache") from None
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ModelManifestError("manifest_outside_cache")
    return tuple(parts)


def _manifest_path_parts(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ModelManifestError("manifest_invalid")
    if value.startswith("/") or "\\" in value or "\x00" in value:
        raise ModelManifestError("manifest_invalid")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ModelManifestError("manifest_invalid")
    if any(any(ord(character) < 32 for character in part) for part in parts):
        raise ModelManifestError("manifest_invalid")
    return tuple(parts)


def _open_relative(
    root_descriptor: int,
    parts: tuple[str, ...],
    *,
    missing_code: str,
    symlink_code: str,
    unreadable_code: str,
) -> int:
    directory_descriptor = os.dup(root_descriptor)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in parts[:-1]:
            try:
                next_descriptor = os.open(part, directory_flags, dir_fd=directory_descriptor)
            except FileNotFoundError:
                raise ModelManifestError(missing_code) from None
            except OSError as exc:
                if exc.errno in {getattr(os, "ELOOP", 40), 40}:
                    raise ModelManifestError(symlink_code) from None
                raise ModelManifestError(unreadable_code) from None
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        try:
            return os.open(parts[-1], file_flags, dir_fd=directory_descriptor)
        except FileNotFoundError:
            raise ModelManifestError(missing_code) from None
        except OSError as exc:
            if exc.errno in {getattr(os, "ELOOP", 40), 40}:
                raise ModelManifestError(symlink_code) from None
            raise ModelManifestError(unreadable_code) from None
    finally:
        os.close(directory_descriptor)


def _read_manifest(root_descriptor: int, parts: tuple[str, ...]) -> bytes:
    descriptor = _open_relative(
        root_descriptor,
        parts,
        missing_code="manifest_missing",
        symlink_code="manifest_symlink",
        unreadable_code="manifest_unreadable",
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ModelManifestError("manifest_unreadable")
        if before.st_size > _MAX_MANIFEST_BYTES:
            raise ModelManifestError("manifest_too_large")
        chunks: list[bytes] = []
        remaining = _MAX_MANIFEST_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(content) > _MAX_MANIFEST_BYTES:
            raise ModelManifestError("manifest_too_large")
        if _changed(before, after) or len(content) != after.st_size:
            raise ModelManifestError("manifest_unreadable")
        return content
    except OSError:
        raise ModelManifestError("manifest_unreadable") from None
    finally:
        os.close(descriptor)


def _changed(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


def _file_signature(status: os.stat_result) -> _FileSignature:
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _safe_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ModelManifestError("manifest_invalid")
    text = value.strip()
    if not text or len(text) > maximum or any(ord(character) < 32 for character in text):
        raise ModelManifestError("manifest_invalid")
    return text


def _exact_keys(value: Mapping[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise ModelManifestError("manifest_invalid")


def _parse_manifest(content: bytes) -> tuple[str, tuple[_Artifact, ...]]:
    try:
        document = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError):
        raise ModelManifestError("manifest_invalid_json") from None
    if not isinstance(document, Mapping):
        raise ModelManifestError("manifest_invalid")
    _exact_keys(document, {"schema_version", "artifacts"})
    schema_version = document.get("schema_version")
    if schema_version != MODEL_MANIFEST_SCHEMA:
        raise ModelManifestError("manifest_schema_unsupported")
    artifact_values = document.get("artifacts")
    if (
        not isinstance(artifact_values, list)
        or not artifact_values
        or len(artifact_values) > _MAX_ARTIFACTS
    ):
        raise ModelManifestError("manifest_invalid")

    artifacts: list[_Artifact] = []
    artifact_keys: set[tuple[str, str, str]] = set()
    file_expectations: dict[tuple[str, ...], tuple[int, str]] = {}
    total_files = 0
    for artifact_value in artifact_values:
        if not isinstance(artifact_value, Mapping):
            raise ModelManifestError("manifest_invalid")
        _exact_keys(
            artifact_value,
            {"role", "model_id", "revision", "license", "files"},
        )
        role = _safe_text(artifact_value.get("role"), maximum=64)
        if _ROLE_RE.fullmatch(role) is None:
            raise ModelManifestError("manifest_invalid")
        model_id = _safe_text(artifact_value.get("model_id"), maximum=256)
        revision = _safe_text(artifact_value.get("revision"), maximum=256)
        if revision.lower() in _FLOATING_REVISIONS:
            raise ModelManifestError("manifest_invalid")
        license_name = _safe_text(artifact_value.get("license"), maximum=128)
        artifact_key = (role, model_id, revision)
        if artifact_key in artifact_keys:
            raise ModelManifestError("manifest_invalid")
        artifact_keys.add(artifact_key)

        file_values = artifact_value.get("files")
        if not isinstance(file_values, list) or not file_values:
            raise ModelManifestError("manifest_invalid")
        total_files += len(file_values)
        if total_files > _MAX_FILES:
            raise ModelManifestError("manifest_invalid")
        files: list[_ExpectedFile] = []
        for file_index, file_value in enumerate(file_values):
            if not isinstance(file_value, Mapping):
                raise ModelManifestError("manifest_invalid")
            _exact_keys(file_value, {"path", "size_bytes", "sha256"})
            parts = _manifest_path_parts(file_value.get("path"))
            size_bytes = file_value.get("size_bytes")
            if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
                raise ModelManifestError("manifest_invalid")
            sha256 = file_value.get("sha256")
            if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
                raise ModelManifestError("manifest_invalid")
            sha256 = sha256.lower()
            previous = file_expectations.get(parts)
            expectation = (size_bytes, sha256)
            if previous is not None and previous != expectation:
                raise ModelManifestError("manifest_invalid")
            file_expectations[parts] = expectation
            files.append(
                _ExpectedFile(
                    parts=parts,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    artifact_role=role,
                    file_index=file_index,
                )
            )
        artifacts.append(
            _Artifact(
                role=role,
                model_id=model_id,
                revision=revision,
                license=license_name,
                files=tuple(files),
            )
        )
    return schema_version, tuple(artifacts)


def _verify_file(
    root_descriptor: int, expected: _ExpectedFile
) -> _FileSignature:
    try:
        descriptor = _open_relative(
            root_descriptor,
            expected.parts,
            missing_code="artifact_missing",
            symlink_code="artifact_symlink",
            unreadable_code="artifact_unreadable",
        )
    except ModelManifestError as exc:
        raise ModelManifestError(
            exc.code,
            artifact_role=expected.artifact_role,
            file_index=expected.file_index,
        ) from None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ModelManifestError(
                "artifact_not_regular",
                artifact_role=expected.artifact_role,
                file_index=expected.file_index,
            )
        if before.st_size != expected.size_bytes:
            raise ModelManifestError(
                "artifact_size_mismatch",
                artifact_role=expected.artifact_role,
                file_index=expected.file_index,
            )
        digest = hashlib.sha256()
        bytes_read = 0
        while True:
            chunk = os.read(descriptor, _HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            bytes_read += len(chunk)
        after = os.fstat(descriptor)
        if _changed(before, after) or bytes_read != expected.size_bytes:
            raise ModelManifestError(
                "artifact_changed",
                artifact_role=expected.artifact_role,
                file_index=expected.file_index,
            )
        if digest.hexdigest() != expected.sha256:
            raise ModelManifestError(
                "artifact_sha256_mismatch",
                artifact_role=expected.artifact_role,
                file_index=expected.file_index,
            )
        return _file_signature(after)
    except ModelManifestError:
        raise
    except OSError:
        raise ModelManifestError(
            "artifact_unreadable",
            artifact_role=expected.artifact_role,
            file_index=expected.file_index,
        ) from None
    finally:
        os.close(descriptor)


def verify_model_manifest(
    cache_root: str | Path,
    manifest_path: str | Path,
) -> ModelReadiness:
    """Verify every unique artifact in an approved local model manifest.

    Successful return is the authorization gate for real model-worker
    construction.  A failure raises :class:`ModelManifestError` whose public
    representation intentionally omits paths and file data.
    """

    root, root_descriptor = _cache_root(cache_root)
    try:
        manifest_parts = _relative_parts(root, manifest_path)
        manifest_content = _read_manifest(root_descriptor, manifest_parts)
        schema_version, artifacts = _parse_manifest(manifest_content)
        verified: dict[tuple[str, ...], _FileSignature] = {}
        for artifact in artifacts:
            for expected in artifact.files:
                if expected.parts not in verified:
                    verified[expected.parts] = _verify_file(
                        root_descriptor, expected
                    )
        artifact_reports = tuple(
            ArtifactReadiness(
                role=artifact.role,
                model_id=artifact.model_id,
                revision=artifact.revision,
                license=artifact.license,
                file_count=len(artifact.files),
                verified_bytes=sum(item.size_bytes for item in artifact.files),
                verified_file_signatures=frozenset(
                    verified[item.parts] for item in artifact.files
                ),
            )
            for artifact in artifacts
        )
        unique_expectations = {
            item.parts: item.size_bytes
            for artifact in artifacts
            for item in artifact.files
        }
        return ModelReadiness(
            schema_version=schema_version,
            manifest_sha256=hashlib.sha256(manifest_content).hexdigest(),
            artifacts=artifact_reports,
            verified_file_count=len(unique_expectations),
            verified_bytes=sum(unique_expectations.values()),
        )
    finally:
        os.close(root_descriptor)


__all__ = [
    "ArtifactReadiness",
    "DEFAULT_MODEL_MANIFEST_NAME",
    "MODEL_MANIFEST_SCHEMA",
    "ModelManifestError",
    "ModelReadiness",
    "verify_model_manifest",
]
