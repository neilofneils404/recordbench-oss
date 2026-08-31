from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from .contracts import (
    ArchiveDestination,
    ArchiveReceipt,
    ClosureRecord,
    ContentOperation,
    IngestionState,
    Matter,
    SourceLocation,
)
from .isolation import AuthorizationError, MatterStateRegistry


class ClosureStage(StrEnum):
    REQUESTED = "requested"
    EXPORTING = "exporting"
    VERIFYING_EXPORTS = "verifying_exports"
    ARCHIVE_HANDOFF = "archive_handoff"
    ARCHIVE_VERIFIED = "archive_verified"
    DISABLING_ACCESS = "disabling_access"
    REMOVING_INDEXES = "removing_indexes"
    PURGING_DERIVED_DATA = "purging_derived_data"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


_ALLOWED_CLOSURE = {
    ClosureStage.REQUESTED: ClosureStage.EXPORTING,
    ClosureStage.EXPORTING: ClosureStage.VERIFYING_EXPORTS,
    ClosureStage.VERIFYING_EXPORTS: ClosureStage.ARCHIVE_HANDOFF,
    ClosureStage.ARCHIVE_VERIFIED: ClosureStage.DISABLING_ACCESS,
    ClosureStage.DISABLING_ACCESS: ClosureStage.REMOVING_INDEXES,
    ClosureStage.REMOVING_INDEXES: ClosureStage.PURGING_DERIVED_DATA,
    ClosureStage.PURGING_DERIVED_DATA: ClosureStage.COMPLETED,
}
_ALLOWED_INGESTION = {
    IngestionState.QUEUED: {IngestionState.RUNNING, IngestionState.CANCELLED},
    IngestionState.RUNNING: {
        IngestionState.SUCCEEDED,
        IngestionState.FAILED,
        IngestionState.CANCELLED,
    },
    IngestionState.FAILED: {IngestionState.QUEUED},
    IngestionState.SUCCEEDED: set(),
    IngestionState.CANCELLED: set(),
}


def advance_ingestion(
    current: IngestionState,
    target: IngestionState,
    registry: MatterStateRegistry,
    matter_id: str,
    *,
    explicit_retry: bool = False,
) -> IngestionState:
    registry.require_active(matter_id, ContentOperation.INGEST)
    if target not in _ALLOWED_INGESTION[current] or (
        current is IngestionState.FAILED and not explicit_retry
    ):
        raise ValueError("invalid ingestion transition")
    return target


def require_active_location(location: SourceLocation) -> SourceLocation:
    if not isinstance(location, SourceLocation):
        raise TypeError("archive destinations are not active locations")
    return location


class ArchiveVerificationError(ValueError):
    pass


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("closure clock must return a timezone-aware UTC datetime")
    return value


class TrustedArchiveAdapter:
    def __init__(
        self, *, clock: Callable[[], datetime], attestation_key: bytes
    ) -> None:
        if not attestation_key:
            raise ValueError("attestation key required")
        self._clock = clock
        self._key = attestation_key

    def verify(
        self,
        matter_id: str,
        closure_run_id: str,
        archive_destination_id: str,
        policy_revision: str,
    ) -> ArchiveReceipt:
        verified_at = _require_utc(self._clock())
        message = "|".join(
            (
                matter_id,
                closure_run_id,
                archive_destination_id,
                policy_revision,
                verified_at.isoformat(),
            )
        )
        attestation = hmac.new(
            self._key, message.encode(), hashlib.sha256
        ).hexdigest()
        return ArchiveReceipt(
            receipt_id=f"receipt-{closure_run_id}",
            matter_id=matter_id,
            closure_run_id=closure_run_id,
            archive_destination_id=archive_destination_id,
            policy_revision=policy_revision,
            verified_at=verified_at,
            adapter_attestation=attestation,
        )

    def accepts(self, receipt: ArchiveReceipt) -> bool:
        message = "|".join(
            (
                receipt.matter_id,
                receipt.closure_run_id,
                receipt.archive_destination_id,
                receipt.policy_revision,
                receipt.verified_at.isoformat(),
            )
        )
        expected = hmac.new(
            self._key, message.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, receipt.adapter_attestation)


@dataclass(frozen=True)
class ClosureRun:
    closure_run_id: str
    matter_id: str
    archive_destination: ArchiveDestination
    source_count: int
    artifact_count: int
    requested_at: datetime
    stage: ClosureStage = ClosureStage.REQUESTED
    receipt: ArchiveReceipt | None = None

    @property
    def policy_revision(self) -> str:
        return self.archive_destination.policy_revision


class ClosureStore:
    def __init__(
        self, *, registry: MatterStateRegistry, clock: Callable[[], datetime]
    ) -> None:
        self._registry = registry
        self._clock = clock
        self._runs: dict[str, ClosureRun] = {}
        self._records: dict[str, ClosureRecord] = {}
        self._trusted: set[TrustedArchiveAdapter] = set()
        self._serial = 0

    def trust_adapter(self, adapter: TrustedArchiveAdapter) -> None:
        self._trusted.add(adapter)

    def request(
        self,
        matter_id: str,
        archive_destination: ArchiveDestination,
        *,
        source_count: int,
        artifact_count: int,
    ) -> ClosureRun:
        if source_count < 0 or artifact_count < 0:
            raise ValueError("closure counts cannot be negative")
        self._serial += 1
        run_id = f"closure-{matter_id}-{self._serial}"
        requested_at = _require_utc(self._clock())
        run = ClosureRun(
            closure_run_id=run_id,
            matter_id=matter_id,
            archive_destination=archive_destination,
            source_count=source_count,
            artifact_count=artifact_count,
            requested_at=requested_at,
        )
        self._registry.begin_closure(matter_id, run_id)
        self._runs[run_id] = run
        return run

    def advance(self, run_id: str, target: ClosureStage) -> ClosureRun:
        run = self._runs[run_id]
        if run.stage == target:
            return run
        if _ALLOWED_CLOSURE.get(run.stage) is not target:
            raise ValueError("closure stages must advance in order")
        if target is ClosureStage.ARCHIVE_VERIFIED:
            raise ArchiveVerificationError(
                "archive verification requires trusted receipt"
            )
        if target is ClosureStage.COMPLETED:
            if run.receipt is None:
                raise ValueError("verified archive receipt is required")
            completed_at = _require_utc(self._clock())
            record = ClosureRecord(
                matter_id=run.matter_id,
                closure_run_id=run_id,
                policy_revision=run.policy_revision,
                source_count=run.source_count,
                artifact_count=run.artifact_count,
                requested_at=run.requested_at,
                completed_at=completed_at,
                receipt_id=run.receipt.receipt_id,
                archive_destination_id=(
                    run.archive_destination.archive_destination_id
                ),
            )
            self._registry.complete_closure(run.matter_id, run_id)
            updated = replace(run, stage=target)
            self._runs[run_id] = updated
            self._records[run_id] = record
            return updated
        updated = replace(run, stage=target)
        self._runs[run_id] = updated
        return updated

    def verify_archive(self, run_id: str, receipt: object) -> ClosureRun:
        run = self._runs[run_id]
        if run.stage is ClosureStage.ARCHIVE_VERIFIED and receipt == run.receipt:
            return run
        if (
            run.stage is not ClosureStage.ARCHIVE_HANDOFF
            or not isinstance(receipt, ArchiveReceipt)
        ):
            raise ArchiveVerificationError("archive handoff is not verifiable")
        destination = run.archive_destination
        if (
            receipt.matter_id != run.matter_id
            or receipt.closure_run_id != run_id
            or receipt.archive_destination_id
            != destination.archive_destination_id
            or receipt.policy_revision != destination.policy_revision
        ):
            raise ArchiveVerificationError("receipt binding mismatch")
        now = _require_utc(self._clock())
        if receipt.verified_at < run.requested_at or receipt.verified_at > now:
            raise ArchiveVerificationError(
                "receipt verification time is outside the closure lifetime"
            )
        if not any(adapter.accepts(receipt) for adapter in self._trusted):
            raise ArchiveVerificationError(
                "receipt is not from a trusted adapter"
            )
        updated = replace(
            run, stage=ClosureStage.ARCHIVE_VERIFIED, receipt=receipt
        )
        self._runs[run_id] = updated
        return updated

    def cancel(self, run_id: str) -> ClosureRun:
        run = self._runs[run_id]
        if run.stage not in {
            ClosureStage.REQUESTED,
            ClosureStage.EXPORTING,
            ClosureStage.VERIFYING_EXPORTS,
            ClosureStage.ARCHIVE_HANDOFF,
        }:
            raise ValueError("cannot cancel after archive verification")
        self._registry.cancel_closure(run.matter_id, run_id)
        updated = replace(run, stage=ClosureStage.CANCELLED)
        self._runs[run_id] = updated
        return updated

    def matter(self, matter_id: str) -> Matter:
        return self._registry.matter(matter_id)

    def is_fenced(self, matter_id: str) -> bool:
        try:
            self._registry.require_active(
                matter_id, ContentOperation.MODEL_CONTEXT
            )
        except AuthorizationError:
            return True
        return False

    def closure_record(self, run_id: str) -> ClosureRecord:
        try:
            return self._records[run_id]
        except KeyError as exc:
            raise ValueError("closure is not complete") from exc
