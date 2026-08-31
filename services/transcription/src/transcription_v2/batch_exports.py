"""Aggregate transient exports for one server-generated upload batch."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .domain import Job
from .exporters import source_export_base_name
from .review_exports import ReviewExportError, refresh_review_exports
from .runtime import Runtime


BATCH_ARCHIVE_ARTIFACT = ".batch-delivery.zip"
BATCH_ARCHIVE_DOWNLOAD_NAME = "transcriptions.zip"
_ARCHIVE_COMMENT_PREFIX = b"transcription-v2-batch-flat-v2:"
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_MAX_EXPORT_BASE_LENGTH = 120
_SAFE_ARCHIVE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,199}$")
_REQUIRED_TAILS = frozenset({".docx", ".txt", ".srt", ".manifest.json"})
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class BatchExportError(RuntimeError):
    """A complete, safe aggregate delivery archive could not be produced."""


@dataclass(frozen=True, slots=True)
class BatchArchive:
    path: Path
    anchor_job_id: str
    included_jobs: int
    omitted_jobs: int


@dataclass(frozen=True, slots=True)
class _ArchiveMember:
    source: Path
    archive_name: str
    content: bytes | None = None


@dataclass(frozen=True, slots=True)
class _PlannedArtifact:
    source: Path
    source_name: str
    archive_name: str


@dataclass(frozen=True, slots=True)
class _JobArchivePlan:
    output: Path
    manifest_source_name: str
    artifacts: tuple[_PlannedArtifact, ...]
    name_map: tuple[tuple[str, str], ...]


def _validate_archive_basename(name: str) -> str:
    """Fail closed unless ``name`` is one portable, extraction-safe component."""

    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or "\x00" in name
        or name.rstrip(" .") != name
        or PurePosixPath(name).is_absolute()
        or PurePosixPath(name).parts != (name,)
        or _SAFE_ARCHIVE_NAME_RE.fullmatch(name) is None
        or name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
    ):
        raise BatchExportError("generated artifact has an unsafe delivery name")
    return name


def _validated_bundle_files(
    bundle: object,
    *,
    output: Path,
    source_base: str,
) -> tuple[tuple[str, Path], ...]:
    """Return only the reviewed export bundle's declared, local artifacts."""

    declared = getattr(bundle, "files", None)
    if not isinstance(declared, Mapping) or not declared:
        raise BatchExportError("reviewed export bundle is unavailable")

    prefix = f"{source_base}."
    resolved_files: dict[str, Path] = {}
    used_names: set[str] = set()
    for raw_name, raw_path in declared.items():
        if not isinstance(raw_name, str):
            raise BatchExportError("reviewed export bundle has an invalid artifact name")
        name = _validate_archive_basename(raw_name)
        folded = name.casefold()
        if folded in used_names:
            raise BatchExportError("reviewed export bundle has duplicate artifact names")
        used_names.add(folded)
        if not name.startswith(prefix) or name.casefold().endswith(".zip"):
            raise BatchExportError("reviewed export bundle has an unexpected artifact")
        try:
            path = Path(raw_path)
            if path.name != name or path.is_symlink() or not path.is_file():
                raise BatchExportError("generated artifacts are unavailable")
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError, TypeError) as exc:
            raise BatchExportError("generated artifacts are unavailable") from exc
        if resolved.parent != output:
            raise BatchExportError("generated artifact escaped its job output directory")
        resolved_files[name] = resolved

    required_names = {f"{source_base}{tail}" for tail in _REQUIRED_TAILS}
    if not required_names.issubset(resolved_files):
        raise BatchExportError("required transcript artifacts are unavailable")

    manifest_name = f"{source_base}.manifest.json"
    try:
        declared_manifest = Path(getattr(bundle, "manifest_path")).resolve(strict=True)
    except (AttributeError, OSError, RuntimeError, TypeError) as exc:
        raise BatchExportError("delivery manifest is unavailable") from exc
    if declared_manifest != resolved_files[manifest_name]:
        raise BatchExportError("delivery manifest does not match its export bundle")

    return tuple(
        sorted(resolved_files.items(), key=lambda item: (item[0].casefold(), item[0]))
    )


def _sequenced_base(preferred: str, sequence: int) -> str:
    suffix = "" if sequence == 1 else f"-{sequence}"
    budget = _MAX_EXPORT_BASE_LENGTH - len(suffix)
    root = preferred[:budget].rstrip(" .") or "transcript"
    return root + suffix


def _allocate_family_base(
    preferred: str,
    tails: tuple[str, ...],
    used_names: set[str],
) -> str:
    """Choose one stem whose complete artifact family is globally unique."""

    for sequence in range(1, 10_001):
        candidate = _sequenced_base(preferred, sequence)
        proposed = [_validate_archive_basename(candidate + tail) for tail in tails]
        folded = [name.casefold() for name in proposed]
        if len(folded) != len(set(folded)):
            raise BatchExportError("one export bundle produced duplicate artifact names")
        if not any(name in used_names for name in folded):
            used_names.update(folded)
            return candidate
    raise BatchExportError("could not allocate unique batch artifact names")


def _build_plans(
    runtime: Runtime,
    owner_key: str,
    jobs: list[Job],
) -> list[_JobArchivePlan]:
    plans: list[_JobArchivePlan] = []
    used_names: set[str] = set()

    for job in jobs:
        files = runtime.store.list_files(job.id, owner_key)
        if len(files) != 1:
            raise BatchExportError("batch jobs must each contain one source recording")
        source_base = source_export_base_name(files[0].safe_name)
        try:
            bundle = refresh_review_exports(runtime, job.id, owner_key)
            output = runtime.storage.job_paths(job.id, create=False).output.resolve()
        except (FileNotFoundError, ReviewExportError, OSError) as exc:
            raise BatchExportError("generated artifacts are unavailable") from exc

        declared = _validated_bundle_files(
            bundle,
            output=output,
            source_base=source_base,
        )
        tails = tuple(name[len(source_base) :] for name, _path in declared)
        if any(not tail.startswith(".") for tail in tails):
            raise BatchExportError("reviewed export bundle has an unexpected artifact")
        archive_base = _allocate_family_base(source_base, tails, used_names)
        name_map = tuple(
            (source_name, archive_base + source_name[len(source_base) :])
            for source_name, _path in declared
        )
        destination_by_source = dict(name_map)
        artifacts = tuple(
            _PlannedArtifact(
                source=path,
                source_name=source_name,
                archive_name=destination_by_source[source_name],
            )
            for source_name, path in declared
        )
        plans.append(
            _JobArchivePlan(
                output=output,
                manifest_source_name=f"{source_base}.manifest.json",
                artifacts=artifacts,
                name_map=name_map,
            )
        )
    return plans


def _validate_planned_source(artifact: _PlannedArtifact, output: Path) -> Path:
    try:
        if artifact.source.is_symlink() or not artifact.source.is_file():
            raise BatchExportError("generated artifacts are unavailable")
        resolved = artifact.source.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BatchExportError("generated artifacts are unavailable") from exc
    if resolved.parent != output or resolved.name != artifact.source_name:
        raise BatchExportError("generated artifact escaped its job output directory")
    return resolved


def _remapped_manifest_content(plan: _JobArchivePlan, manifest_path: Path) -> bytes:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BatchExportError("delivery manifest is invalid") from exc
    if not isinstance(payload, dict):
        raise BatchExportError("delivery manifest is invalid")

    name_map = dict(plan.name_map)
    artifacts = payload.get("artifacts")
    delivery = payload.get("delivery")
    expected_artifacts = set(name_map) - {plan.manifest_source_name}
    if (
        not isinstance(artifacts, Mapping)
        or not all(isinstance(name, str) for name in artifacts)
        or set(artifacts) != expected_artifacts
        or not isinstance(delivery, Mapping)
    ):
        raise BatchExportError("delivery manifest does not match its export bundle")

    payload["artifacts"] = {
        name_map[name]: artifacts[name]
        for name in sorted(artifacts, key=lambda value: (value.casefold(), value))
    }
    remapped_delivery = dict(delivery)
    remapped_delivery["archive_file"] = BATCH_ARCHIVE_DOWNLOAD_NAME
    remapped_delivery["archive_layout"] = "flat"
    payload["delivery"] = remapped_delivery
    try:
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError) as exc:
        raise BatchExportError("delivery manifest is invalid") from exc
    return rendered.encode("utf-8")


def _members_from_plans(plans: list[_JobArchivePlan]) -> list[_ArchiveMember]:
    members: list[_ArchiveMember] = []
    for plan in plans:
        for artifact in plan.artifacts:
            source = _validate_planned_source(artifact, plan.output)
            content = (
                _remapped_manifest_content(plan, source)
                if artifact.source_name == plan.manifest_source_name
                else None
            )
            members.append(
                _ArchiveMember(
                    source=source,
                    archive_name=_validate_archive_basename(artifact.archive_name),
                    content=content,
                )
            )

    members.sort(key=lambda item: (item.archive_name.casefold(), item.archive_name))
    names = [member.archive_name.casefold() for member in members]
    if len(names) != len(set(names)):
        raise BatchExportError("batch archive would contain duplicate artifact names")
    return members


def _fingerprint(batch_id: str, jobs: list[Job], members: list[_ArchiveMember]) -> bytes:
    digest = hashlib.sha256()
    digest.update(batch_id.encode("ascii"))
    digest.update(b"\0")
    for job in jobs:
        digest.update(job.id.encode("ascii"))
        digest.update(b"\0")
    for member in members:
        digest.update(member.archive_name.encode("utf-8"))
        digest.update(b"\0")
        if member.content is not None:
            digest.update(member.content)
        else:
            try:
                with member.source.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError as exc:
                raise BatchExportError("generated artifacts changed during packaging") from exc
        digest.update(b"\0")
    return _ARCHIVE_COMMENT_PREFIX + digest.hexdigest().encode("ascii")


def _valid_cached_archive(
    path: Path,
    expected_comment: bytes,
    expected_names: tuple[str, ...],
) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = tuple(item.filename for item in archive.infolist())
            for name in names:
                _validate_archive_basename(name)
            return (
                archive.comment == expected_comment
                and names == expected_names
                and len({name.casefold() for name in names}) == len(names)
                and archive.testzip() is None
            )
    except (
        BatchExportError,
        EOFError,
        OSError,
        RuntimeError,
        zipfile.BadZipFile,
        zlib.error,
    ):
        return False


def _write_archive(path: Path, members: list[_ArchiveMember], comment: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".batch-delivery-", suffix=".part", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            allowZip64=True,
        ) as archive:
            for member in members:
                info = zipfile.ZipInfo(member.archive_name, date_time=_FIXED_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100600 << 16
                with archive.open(info, mode="w", force_zip64=True) as destination:
                    if member.content is not None:
                        destination.write(member.content)
                    else:
                        with member.source.open("rb") as source:
                            shutil.copyfileobj(source, destination, length=1024 * 1024)
            archive.comment = comment
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o400)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise BatchExportError("batch delivery archive could not be written") from exc
    finally:
        temporary.unlink(missing_ok=True)


def build_or_reuse_batch_archive(
    runtime: Runtime,
    *,
    owner_key: str,
    batch_id: str,
    succeeded_jobs: list[Job],
    omitted_jobs: int,
) -> BatchArchive:
    """Create a content-current, root-flat ZIP below the first successful job."""

    if not succeeded_jobs:
        raise BatchExportError("a batch archive requires at least one successful job")
    ordered = sorted(succeeded_jobs, key=lambda job: (job.created_at, job.id))
    anchor = ordered[0]
    try:
        anchor_output = runtime.storage.job_paths(anchor.id, create=False).output.resolve()
    except (FileNotFoundError, OSError) as exc:
        raise BatchExportError("batch output directory is unavailable") from exc
    archive_path = anchor_output / BATCH_ARCHIVE_ARTIFACT
    if archive_path.exists() and (archive_path.is_symlink() or not archive_path.is_file()):
        raise BatchExportError("batch archive path is unsafe")

    # If an optional review update races packaging, retry from a fresh export
    # snapshot rather than returning an archive assembled across revisions.
    for _attempt in range(3):
        plans = _build_plans(runtime, owner_key, ordered)
        members = _members_from_plans(plans)
        expected_names = tuple(member.archive_name for member in members)
        comment = _fingerprint(batch_id, ordered, members)
        if _valid_cached_archive(archive_path, comment, expected_names):
            return BatchArchive(
                path=archive_path,
                anchor_job_id=anchor.id,
                included_jobs=len(ordered),
                omitted_jobs=omitted_jobs,
            )
        _write_archive(archive_path, members, comment)
        # Re-hash without regenerating every per-job export a second time. A
        # concurrent edit that refreshes an artifact still changes this pass's
        # fingerprint and triggers the bounded retry.
        current_members = _members_from_plans(plans)
        current_names = tuple(member.archive_name for member in current_members)
        current_comment = _fingerprint(batch_id, ordered, current_members)
        if (
            current_names == expected_names
            and current_comment == comment
            and _valid_cached_archive(archive_path, comment, expected_names)
        ):
            return BatchArchive(
                path=archive_path,
                anchor_job_id=anchor.id,
                included_jobs=len(ordered),
                omitted_jobs=omitted_jobs,
            )
    raise BatchExportError("generated artifacts kept changing during packaging")


__all__ = [
    "BATCH_ARCHIVE_ARTIFACT",
    "BATCH_ARCHIVE_DOWNLOAD_NAME",
    "BatchArchive",
    "BatchExportError",
    "build_or_reuse_batch_archive",
]
