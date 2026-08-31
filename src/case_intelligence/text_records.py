from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .contracts import (
    PersistedSourceVersion,
    SourceFileRecord,
    SourceFileAvailability,
    SourceLocator,
    SourceReference,
)
from .isolation import ReferenceResolution, ReferenceResolutionStatus


@dataclass(frozen=True)
class PlainTextRecord:
    segment_id: str
    representation_id: str
    matter_id: str
    source_file_id: str
    source_version_id: str
    text: str
    text_sha256: str
    character_start: int
    character_end: int
    line_start: int
    line_end: int
    exact_keys: tuple[str, ...]
    locator: SourceLocator


def build_plain_text_record(source: PersistedSourceVersion, payload: bytes) -> PlainTextRecord:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("plain text must be strict UTF-8") from exc
    if not text:
        raise ValueError("plain text cannot be empty")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != source.sha256 or len(payload) != source.byte_size:
        raise ValueError("source bytes do not match immutable version")
    representation_id = f"representation-{source.source_version_id}"
    segment_id = f"segment-{source.source_version_id}-1"
    keys = sorted(set(re.findall(r"\b(?:[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+|[A-Z]+\d{4,})\b", text)))
    line_count = text.count("\n") + (0 if text.endswith("\n") else 1)
    locator = SourceLocator(
        representation_id=representation_id,
        segment_id=segment_id,
        character_start=0,
        character_end=len(text),
        line_start=1,
        line_end=line_count + 1,
        excerpt_sha256=digest,
    )
    return PlainTextRecord(segment_id, representation_id, source.matter_id,
                           source.source_file_id, source.source_version_id, text,
                           digest, 0, len(text), 1, line_count + 1,
                           tuple(keys), locator)


def resolve_persisted_reference(
    authorized_matter_id: str,
    reference: SourceReference,
    source_file: SourceFileRecord | None,
    source_version: PersistedSourceVersion | None,
    *,
    record: PlainTextRecord | None = None,
    excerpt_sha256: str | None = None,
) -> ReferenceResolution:
    if reference.matter_id != authorized_matter_id:
        return ReferenceResolution(ReferenceResolutionStatus.UNAUTHORIZED)
    if source_file is None or source_version is None:
        return ReferenceResolution(ReferenceResolutionStatus.VERSION_MISMATCH)
    if (source_file.matter_id != authorized_matter_id or
        source_version.matter_id != authorized_matter_id):
        return ReferenceResolution(ReferenceResolutionStatus.UNAUTHORIZED)
    if (reference.source_version_id != source_version.source_version_id or
        source_version.source_file_id != source_file.source_file_id or
        source_version.source_location_id != source_file.source_location_id or
        source_version.relative_path != source_file.relative_path):
        return ReferenceResolution(ReferenceResolutionStatus.VERSION_MISMATCH)
    if source_file.availability is SourceFileAvailability.MISSING:
        return ReferenceResolution(ReferenceResolutionStatus.UNAVAILABLE)
    if source_file.current_source_version_id != source_version.source_version_id:
        return ReferenceResolution(ReferenceResolutionStatus.STALE)
    locator = reference.locator
    if record is None or (
        hashlib.sha256(record.text.encode("utf-8")).hexdigest() != record.text_sha256 or
        record.text_sha256 != source_version.sha256 or
        record.matter_id != authorized_matter_id or
        record.source_file_id != source_file.source_file_id or
        record.source_version_id != source_version.source_version_id or
        locator.representation_id != record.representation_id or
        locator.segment_id != record.segment_id or
        locator.character_start != record.character_start or
        locator.character_end != record.character_end or
        locator.line_start != record.line_start or
        locator.line_end != record.line_end or
        locator.excerpt_sha256 != record.text_sha256 or
        excerpt_sha256 != record.text_sha256
    ):
        return ReferenceResolution(ReferenceResolutionStatus.INVALID_REFERENCE)
    return ReferenceResolution(ReferenceResolutionStatus.RESOLVED)


def exact_keys_json(record: PlainTextRecord) -> str:
    return json.dumps(record.exact_keys, ensure_ascii=False, separators=(",", ":"))
