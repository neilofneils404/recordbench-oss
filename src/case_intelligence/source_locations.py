"""Read-only, administrator-registered discovery source locations.

The browser receives labels and relative paths only.  Linux roots are loaded
from protected server configuration and every read is resolved beneath a held
root descriptor without following symbolic links.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .contracts import validate_relative_path
from .fixture_builder import _FILE_READ_FLAGS, _open_directory_path, _openat2_beneath
from .pilot_uploads import CHUNK_BYTES, DOCX_MEDIA_TYPE

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
_LOCATION_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": DOCX_MEDIA_TYPE,
    ".txt": "text/plain",
}


class SourceLocationProblem(ValueError):
    """A safe-to-display registered-source failure."""


@dataclass(frozen=True)
class SourceScanLimits:
    max_files: int = 20_000
    max_depth: int = 32
    max_file_bytes: int = 512 * 1024 * 1024
    max_aggregate_bytes: int = 2 * 1024 * 1024 * 1024 * 1024
    max_path_bytes: int = 2_048


@dataclass(frozen=True)
class RegisteredSourceLocation:
    source_location_id: str
    label: str
    root: Path

    def staff_projection(self) -> dict[str, str]:
        return {"source_location_id": self.source_location_id, "label": self.label}


@dataclass(frozen=True)
class SourceScanItem:
    relative_path: str
    display_name: str
    media_type: str
    byte_size: int
    stable_device: int
    stable_inode: int
    stable_mtime_ns: int


@dataclass(frozen=True)
class SourcePreflight:
    source_location_id: str
    label: str
    relative_folder: str
    supported: tuple[SourceScanItem, ...]
    unsupported_count: int
    total_bytes: int


@dataclass(frozen=True)
class StagedSource:
    path: Path
    sha256: str
    byte_size: int


class SourceLocationRegistry:
    """Bounded scanner and stable copier for pre-registered read-only roots."""

    def __init__(
        self,
        locations: Mapping[str, RegisteredSourceLocation] | tuple[RegisteredSourceLocation, ...] = (),
        *,
        limits: SourceScanLimits = SourceScanLimits(),
    ) -> None:
        values = locations.values() if isinstance(locations, Mapping) else locations
        prepared: dict[str, RegisteredSourceLocation] = {}
        for location in values:
            self._validate_location(location)
            if location.source_location_id in prepared:
                raise ValueError("duplicate source location identifier")
            prepared[location.source_location_id] = location
        self._locations = prepared
        self.limits = limits

    @classmethod
    def from_json(cls, path: Path, *, limits: SourceScanLimits = SourceScanLimits()) -> "SourceLocationRegistry":
        config = Path(path)
        parent_fd = -1
        descriptor = -1
        try:
            _, parent_fd = _open_directory_path(
                config.parent, label="source location configuration directory"
            )
            descriptor = os.open(
                config.name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_size > 1024 * 1024:
                raise RuntimeError("source location configuration is not a bounded regular file")
            if details.st_mode & 0o022 or details.st_uid not in {0, os.getuid()}:
                raise RuntimeError("source location configuration permissions are unsafe")
            with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
                descriptor = -1
                payload = json.load(stream)
            raw_locations = payload["locations"]
            if set(payload) != {"version", "locations"} or payload["version"] != 1:
                raise ValueError
            if not isinstance(raw_locations, list):
                raise ValueError
            locations = tuple(
                RegisteredSourceLocation(
                    source_location_id=item["id"],
                    label=item["label"],
                    root=Path(item["root"]),
                )
                for item in raw_locations
                if isinstance(item, dict) and set(item) == {"id", "label", "root"}
            )
            if len(locations) != len(raw_locations):
                raise ValueError
        except RuntimeError:
            raise
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("source location configuration is invalid") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if parent_fd >= 0:
                os.close(parent_fd)
        return cls(locations, limits=limits)

    @staticmethod
    def _validate_location(location: RegisteredSourceLocation) -> None:
        if not _LOCATION_ID.fullmatch(location.source_location_id):
            raise ValueError("invalid source location identifier")
        label = unicodedata.normalize("NFC", location.label or "").strip()
        if (
            not label
            or len(label) > 100
            or any(unicodedata.category(character) in {"Cc", "Cf"} for character in label)
        ):
            raise ValueError("invalid source location label")
        if label != location.label:
            raise ValueError("source location label must be normalized")
        if not location.root.is_absolute():
            raise ValueError("source location root must be absolute")

    def staff_locations(self) -> tuple[dict[str, str], ...]:
        return tuple(
            location.staff_projection()
            for location in sorted(self._locations.values(), key=lambda item: item.label.casefold())
        )

    def _location(self, source_location_id: str) -> RegisteredSourceLocation:
        try:
            return self._locations[source_location_id]
        except KeyError as exc:
            raise SourceLocationProblem("That registered source location is unavailable.") from exc

    @staticmethod
    def _folder(value: str) -> str:
        folder = unicodedata.normalize("NFC", (value or "").strip().strip("/"))
        if not folder:
            return ""
        try:
            return validate_relative_path(folder)
        except ValueError as exc:
            raise SourceLocationProblem("Choose a normal folder beneath the registered location.") from exc

    def preflight(self, source_location_id: str, relative_folder: str = "") -> SourcePreflight:
        location = self._location(source_location_id)
        folder = self._folder(relative_folder)
        try:
            _, root_fd = _open_directory_path(location.root, label="registered source root")
        except (OSError, ValueError) as exc:
            raise SourceLocationProblem("That registered source location is unavailable.") from exc
        scan_fd = -1
        try:
            if folder:
                try:
                    scan_fd = _openat2_beneath(root_fd, folder, _DIRECTORY_FLAGS)
                except (OSError, RuntimeError) as exc:
                    raise SourceLocationProblem("That folder is unavailable beneath the registered location.") from exc
            else:
                scan_fd = os.dup(root_fd)
            supported: list[SourceScanItem] = []
            counts = [0, 0]
            self._enumerate(scan_fd, folder, 0, supported, counts)
            supported.sort(key=lambda item: item.relative_path.encode("utf-8"))
            windows_keys = [
                tuple(component.rstrip(" .").casefold() for component in item.relative_path.split("/"))
                for item in supported
            ]
            if len(windows_keys) != len(set(windows_keys)):
                raise SourceLocationProblem(
                    "The folder contains source names that are ambiguous on staff workstations."
                )
            total_bytes = sum(item.byte_size for item in supported)
            if total_bytes > self.limits.max_aggregate_bytes:
                raise SourceLocationProblem("That folder is too large for one import plan.")
            return SourcePreflight(
                source_location_id,
                location.label,
                folder,
                tuple(supported),
                counts[1],
                total_bytes,
            )
        finally:
            if scan_fd >= 0:
                os.close(scan_fd)
            os.close(root_fd)

    def _enumerate(
        self,
        directory_fd: int,
        prefix: str,
        depth: int,
        supported: list[SourceScanItem],
        counts: list[int],
    ) -> None:
        if depth > self.limits.max_depth:
            raise SourceLocationProblem("That folder is nested too deeply for one import plan.")
        try:
            with os.scandir(directory_fd) as scanned:
                entries = sorted(scanned, key=lambda item: os.fsencode(item.name))
        except OSError as exc:
            raise SourceLocationProblem("The registered folder could not be enumerated.") from exc
        for entry in entries:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            try:
                validate_relative_path(relative)
            except ValueError as exc:
                raise SourceLocationProblem("The folder contains an unsafe or ambiguous path.") from exc
            if len(relative.encode("utf-8")) > self.limits.max_path_bytes:
                raise SourceLocationProblem("The folder contains a path that is too long.")
            if entry.is_symlink():
                raise SourceLocationProblem("The folder contains a symbolic link; symbolic links are not imported.")
            if entry.is_dir(follow_symlinks=False):
                try:
                    child = os.open(entry.name, _DIRECTORY_FLAGS, dir_fd=directory_fd)
                except OSError as exc:
                    raise SourceLocationProblem("A source folder changed during review.") from exc
                try:
                    self._enumerate(child, relative, depth + 1, supported, counts)
                finally:
                    os.close(child)
                continue
            counts[0] += 1
            if counts[0] > self.limits.max_files:
                raise SourceLocationProblem("That folder contains too many files for one import plan.")
            if not entry.is_file(follow_symlinks=False):
                raise SourceLocationProblem("The folder contains a non-file item that cannot be imported.")
            media_type = _MEDIA_TYPES.get(Path(entry.name).suffix.casefold())
            if media_type is None:
                counts[1] += 1
                continue
            details = entry.stat(follow_symlinks=False)
            if details.st_size <= 0:
                counts[1] += 1
                continue
            if details.st_size > self.limits.max_file_bytes:
                counts[1] += 1
                continue
            supported.append(
                SourceScanItem(
                    relative,
                    entry.name,
                    media_type,
                    details.st_size,
                    details.st_dev,
                    details.st_ino,
                    details.st_mtime_ns,
                )
            )

    def stage(self, source_location_id: str, item: SourceScanItem, destination: Path) -> StagedSource:
        """Copy exactly one preflighted file without modifying its source."""

        location = self._location(source_location_id)
        try:
            validate_relative_path(item.relative_path)
        except ValueError as exc:
            raise SourceLocationProblem("The queued source path is invalid.") from exc
        stage_root = Path(destination)
        if stage_root.is_symlink() or not stage_root.is_dir():
            raise RuntimeError("source staging directory is unsafe")
        try:
            _, root_fd = _open_directory_path(location.root, label="registered source root")
        except (OSError, ValueError) as exc:
            raise SourceLocationProblem("That registered source location is unavailable.") from exc
        source_fd = -1
        stage_path = stage_root / f".source-{uuid.uuid4().hex}.part"
        output_fd = -1
        try:
            try:
                source_fd = _openat2_beneath(root_fd, item.relative_path, _FILE_READ_FLAGS)
            except (OSError, RuntimeError) as exc:
                raise SourceLocationProblem("A queued source is no longer available.") from exc
            before = os.fstat(source_fd)
            expected = (
                item.stable_device,
                item.stable_inode,
                item.byte_size,
                item.stable_mtime_ns,
            )
            observed = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            if not stat.S_ISREG(before.st_mode) or observed != expected:
                raise SourceLocationProblem("A queued source changed after review; review the folder again.")
            output_fd = os.open(
                stage_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
            )
            digest = hashlib.sha256()
            copied = 0
            while chunk := os.read(source_fd, CHUNK_BYTES):
                copied += len(chunk)
                if copied > self.limits.max_file_bytes:
                    raise SourceLocationProblem("A queued source exceeds the import size limit.")
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(output_fd, view)
                    if written <= 0:
                        raise SourceLocationProblem("A queued source could not be staged safely.")
                    view = view[written:]
            os.fsync(output_fd)
            after = os.fstat(source_fd)
            final_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            if final_identity != expected or copied != item.byte_size:
                raise SourceLocationProblem("A queued source changed while it was being copied.")
            return StagedSource(stage_path, digest.hexdigest(), copied)
        except BaseException:
            stage_path.unlink(missing_ok=True)
            raise
        finally:
            if output_fd >= 0:
                os.close(output_fd)
            if source_fd >= 0:
                os.close(source_fd)
            os.close(root_fd)


def source_registry_from_environment() -> SourceLocationRegistry:
    """Load optional protected configuration without inventing filesystem roots."""

    configured = os.getenv("CASE_INTELLIGENCE_SOURCE_LOCATIONS_FILE", "").strip()
    return SourceLocationRegistry.from_json(Path(configured)) if configured else SourceLocationRegistry()
