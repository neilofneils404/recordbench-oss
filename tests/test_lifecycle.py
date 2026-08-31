import pytest

from case_intelligence.contracts import (
    ArchiveDestination,
    ContentOperation,
    IngestionState,
    LocationKind,
    MatterState,
)
from case_intelligence.isolation import (
    AuthorizationError,
    MatterStateRegistry,
    guard_content_operation,
)
from case_intelligence.lifecycle import (
    ArchiveVerificationError,
    ClosureStage,
    ClosureStore,
    TrustedArchiveAdapter,
    advance_ingestion,
    require_active_location,
)
from tests.support import ALPHA, NOW, location, matter


def destination(destination_id: str = "archive-test") -> ArchiveDestination:
    return ArchiveDestination(
        archive_destination_id=destination_id,
        display_name="Synthetic archive",
        policy_revision="policy-1",
    )


def closure_store() -> tuple[ClosureStore, MatterStateRegistry]:
    registry = MatterStateRegistry([matter()])
    return ClosureStore(registry=registry, clock=lambda: NOW), registry


def request(store: ClosureStore, archive: ArchiveDestination | None = None):
    return store.request(
        ALPHA,
        archive or destination(),
        source_count=3,
        artifact_count=2,
    )


def test_ingestion_transition_table_and_nonactive_retry() -> None:
    active = MatterStateRegistry([matter()])
    assert (
        advance_ingestion(
            IngestionState.QUEUED,
            IngestionState.RUNNING,
            active,
            ALPHA,
        )
        is IngestionState.RUNNING
    )
    assert (
        advance_ingestion(
            IngestionState.FAILED,
            IngestionState.QUEUED,
            active,
            ALPHA,
            explicit_retry=True,
        )
        is IngestionState.QUEUED
    )
    with pytest.raises(ValueError):
        advance_ingestion(
            IngestionState.SUCCEEDED,
            IngestionState.RUNNING,
            active,
            ALPHA,
        )
    closing = MatterStateRegistry([matter(state=MatterState.CLOSING)])
    with pytest.raises(AuthorizationError):
        advance_ingestion(
            IngestionState.FAILED,
            IngestionState.QUEUED,
            closing,
            ALPHA,
            explicit_retry=True,
        )


def test_archive_destination_cannot_be_active_location() -> None:
    archive = destination()
    with pytest.raises(TypeError):
        require_active_location(archive)
    assert (
        require_active_location(location(kind=LocationKind.WORK_PRODUCT_OUTPUT)).kind
        is LocationKind.WORK_PRODUCT_OUTPUT
    )


def test_archive_failure_or_untrusted_receipt_cannot_close() -> None:
    store, _ = closure_store()
    run = request(store)
    store.advance(run.closure_run_id, ClosureStage.EXPORTING)
    store.advance(run.closure_run_id, ClosureStage.VERIFYING_EXPORTS)
    store.advance(run.closure_run_id, ClosureStage.ARCHIVE_HANDOFF)
    with pytest.raises(ArchiveVerificationError):
        store.verify_archive(run.closure_run_id, object())
    assert store.matter(ALPHA).state is MatterState.CLOSING


def test_verified_archive_fences_before_purge_and_callbacks_are_idempotent() -> None:
    store, registry = closure_store()
    adapter = TrustedArchiveAdapter(
        clock=lambda: NOW, attestation_key=b"synthetic-test-key"
    )
    archive = destination()
    run = request(store, archive)
    for stage in (
        ClosureStage.EXPORTING,
        ClosureStage.VERIFYING_EXPORTS,
        ClosureStage.ARCHIVE_HANDOFF,
    ):
        store.advance(run.closure_run_id, stage)
    receipt = adapter.verify(
        ALPHA,
        run.closure_run_id,
        archive.archive_destination_id,
        archive.policy_revision,
    )
    store.trust_adapter(adapter)
    store.verify_archive(run.closure_run_id, receipt)
    store.verify_archive(run.closure_run_id, receipt)
    assert store.is_fenced(ALPHA)
    with pytest.raises(AuthorizationError):
        guard_content_operation(registry, ALPHA, ContentOperation.RETRIEVE)
    for stage in (
        ClosureStage.DISABLING_ACCESS,
        ClosureStage.REMOVING_INDEXES,
        ClosureStage.PURGING_DERIVED_DATA,
        ClosureStage.COMPLETED,
    ):
        store.advance(run.closure_run_id, stage)
    assert store.matter(ALPHA).state is MatterState.CLOSED
    record = store.closure_record(run.closure_run_id)
    dumped = record.model_dump()
    assert not (
        {
            "display_name",
            "path",
            "filename",
            "evidence",
            "transcript",
            "prompt",
            "conversation",
        }
        & dumped.keys()
    )


def test_cancellation_allowed_only_before_archive_verification() -> None:
    store, _ = closure_store()
    first = request(store)
    store.cancel(first.closure_run_id)
    assert store.matter(ALPHA).state is MatterState.ACTIVE


def test_completed_and_cancelled_closure_runs_are_terminal() -> None:
    store, _ = closure_store()
    adapter = TrustedArchiveAdapter(
        clock=lambda: NOW, attestation_key=b"synthetic-test-key"
    )
    store.trust_adapter(adapter)
    archive = destination()
    run = request(store, archive)
    for stage in (
        ClosureStage.EXPORTING,
        ClosureStage.VERIFYING_EXPORTS,
        ClosureStage.ARCHIVE_HANDOFF,
    ):
        store.advance(run.closure_run_id, stage)
    receipt = adapter.verify(
        ALPHA,
        run.closure_run_id,
        archive.archive_destination_id,
        archive.policy_revision,
    )
    store.verify_archive(run.closure_run_id, receipt)
    with pytest.raises(ValueError):
        store.cancel(run.closure_run_id)
    for stage in (
        ClosureStage.DISABLING_ACCESS,
        ClosureStage.REMOVING_INDEXES,
        ClosureStage.PURGING_DERIVED_DATA,
        ClosureStage.COMPLETED,
    ):
        store.advance(run.closure_run_id, stage)
    with pytest.raises(ValueError):
        store.advance(run.closure_run_id, ClosureStage.CANCELLED)
    with pytest.raises(ValueError):
        store.cancel(run.closure_run_id)

    other, _ = closure_store()
    cancelled = request(other)
    other.cancel(cancelled.closure_run_id)
    with pytest.raises(ValueError):
        other.advance(cancelled.closure_run_id, ClosureStage.EXPORTING)


def test_closure_record_uses_bound_destination() -> None:
    store, _ = closure_store()
    adapter = TrustedArchiveAdapter(
        clock=lambda: NOW, attestation_key=b"synthetic-test-key"
    )
    store.trust_adapter(adapter)
    archive = destination("archive-trusted")
    run = request(store, archive)
    for stage in (
        ClosureStage.EXPORTING,
        ClosureStage.VERIFYING_EXPORTS,
        ClosureStage.ARCHIVE_HANDOFF,
    ):
        store.advance(run.closure_run_id, stage)
    store.verify_archive(
        run.closure_run_id,
        adapter.verify(
            ALPHA,
            run.closure_run_id,
            archive.archive_destination_id,
            archive.policy_revision,
        ),
    )
    for stage in (
        ClosureStage.DISABLING_ACCESS,
        ClosureStage.REMOVING_INDEXES,
        ClosureStage.PURGING_DERIVED_DATA,
        ClosureStage.COMPLETED,
    ):
        store.advance(run.closure_run_id, stage)
    assert (
        store.closure_record(run.closure_run_id).archive_destination_id
        == "archive-trusted"
    )


def test_duplicate_closure_request_cannot_bypass_registry_with_stale_state() -> None:
    store, _ = closure_store()
    request(store)
    with pytest.raises(ValueError):
        request(store)
