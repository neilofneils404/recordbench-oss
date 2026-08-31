"""Regenerate transient delivery artifacts from saved human review state."""

from __future__ import annotations

import json
import os
import re
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import fcntl

from .domain import IdentityStatus
from .exporters import ExportBundle, source_export_base_name, write_export_bundle
from .runtime import Runtime


class ReviewExportError(RuntimeError):
    pass


_LEGACY_EXPORT_NAME = re.compile(
    r"^transcript\.(?:"
    r"docx|json|txt|srt|vtt|csv|manifest\.json|delivery\.zip|"
    r"translation\.[A-Za-z0-9_-]{1,32}\.(?:docx|json|txt|srt|vtt)"
    r")$"
)


def _retire_legacy_exports(
    output: Path,
    *,
    export_base_name: str,
    bundle: ExportBundle,
) -> None:
    """Remove only superseded pre-source-name artifacts after validation."""

    required = {
        f"{export_base_name}.docx",
        f"{export_base_name}.txt",
        f"{export_base_name}.srt",
        f"{export_base_name}.manifest.json",
    }
    if bundle.zip_path is None or not required.issubset(bundle.files):
        raise ReviewExportError("source-named delivery bundle is incomplete")
    try:
        with zipfile.ZipFile(bundle.zip_path, "r") as archive:
            if archive.testzip() is not None or not required.issubset(archive.namelist()):
                raise ReviewExportError("source-named delivery bundle is invalid")
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ReviewExportError("source-named delivery bundle is invalid") from exc

    current_names = set(bundle.files)
    current_names.add(bundle.zip_path.name)
    for candidate in output.iterdir():
        if (
            _LEGACY_EXPORT_NAME.fullmatch(candidate.name)
            and candidate.name not in current_names
            and not candidate.is_symlink()
            and candidate.is_file()
        ):
            candidate.unlink()


@contextmanager
def _job_export_lock(runtime: Runtime, job_id: str) -> Iterator[None]:
    work = runtime.storage.job_paths(job_id, create=False).work
    lock_path = work / ".review-export.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.chmod(lock_path, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def refresh_review_exports(runtime: Runtime, job_id: str, owner_key: str) -> ExportBundle:
    """Serialize and atomically rebuild delivery files from current review state."""

    try:
        with _job_export_lock(runtime, job_id):
            return _refresh_review_exports_locked(runtime, job_id, owner_key)
    except ReviewExportError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ReviewExportError("reviewed delivery packaging failed") from exc


def _refresh_review_exports_locked(
    runtime: Runtime, job_id: str, owner_key: str
) -> ExportBundle:
    job = runtime.store.get_owned_job(job_id, owner_key)
    files = runtime.store.list_files(job.id, owner_key)
    if len(files) != 1:
        raise ReviewExportError("reviewed delivery requires exactly one source file")
    export_base_name = source_export_base_name(files[0].safe_name)
    machine_path = runtime.storage.job_paths(job_id, create=False).work / "machine-result.json"
    try:
        payload = json.loads(machine_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewExportError("immutable machine result is unavailable") from exc
    if not isinstance(payload, dict):
        raise ReviewExportError("immutable machine result is invalid")

    reviewed = runtime.store.list_segments(job_id, owner_key)
    mappings = {
        mapping.speaker_key: mapping
        for mapping in runtime.store.list_speaker_mappings(job_id, owner_key)
    }
    machine_segments = payload.get("segments")
    if not isinstance(machine_segments, list) or len(machine_segments) != len(reviewed):
        raise ReviewExportError("review state no longer matches machine output")

    for machine, segment in zip(machine_segments, reviewed):
        if not isinstance(machine, dict):
            raise ReviewExportError("machine segment is invalid")
        machine["model_text"] = segment.model_text
        machine["text"] = segment.text
        machine["translated_text"] = segment.translated_text
        machine["review_revision"] = segment.revision
        machine["overlap"] = segment.overlap
        machine["confidence"] = segment.confidence
        machine["speaker_cluster"] = segment.speaker_key
        mapping = mappings.get(segment.speaker_key or "")
        if mapping is not None:
            machine["speaker"] = mapping.display_name
            machine["speaker_identity"] = {
                "cluster": mapping.speaker_key,
                "status": mapping.identity_status.value,
                "method": mapping.identity_method.value,
                "confidence": mapping.confidence,
                "revision": mapping.revision,
            }

    reviewed_items = [segment for segment in reviewed if segment.revision > 1]
    reviewed_mappings = [
        mapping
        for mapping in mappings.values()
        if mapping.revision > 1
        or mapping.identity_status is IdentityStatus.CONFIRMED
    ]
    human_reviewed = bool(reviewed_items or reviewed_mappings)
    review_timestamps = [item.updated_at for item in reviewed_items]
    review_timestamps.extend(item.updated_at for item in reviewed_mappings)
    reviewed_at = max(review_timestamps) if review_timestamps else None
    provenance = payload.setdefault("provenance", {})
    if not isinstance(provenance, dict):
        provenance = {}
        payload["provenance"] = provenance
    provenance["review"] = {
        "state": "human_reviewed" if human_reviewed else "machine_draft",
        "reviewed_at": reviewed_at,
        "segment_revision_total": sum(segment.revision for segment in reviewed),
        "speaker_mapping_revision_total": sum(mapping.revision for mapping in mappings.values()),
        "source_model_text_preserved": True,
    }
    payload["speaker_mappings"] = [
        {
            "cluster": mapping.speaker_key,
            "display_name": mapping.display_name,
            "identity_status": mapping.identity_status.value,
            "identity_method": mapping.identity_method.value,
            "confidence": mapping.confidence,
            "revision": mapping.revision,
        }
        for mapping in sorted(mappings.values(), key=lambda item: item.speaker_key)
    ]
    # ``translated_text`` on a source segment is a review convenience derived
    # from approximate overlap.  It is not an independently reviewed or forced-
    # aligned translation, so it must never replace the canonical translation
    # artifact saved by the model pipeline.
    output = runtime.storage.job_paths(job.id, create=False).output
    bundle = write_export_bundle(
        payload,
        output,
        base_name=export_base_name,
        create_zip=True,
    )
    _retire_legacy_exports(
        output,
        export_base_name=export_base_name,
        bundle=bundle,
    )
    return bundle


__all__ = ["ReviewExportError", "refresh_review_exports"]
