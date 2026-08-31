from datetime import timedelta

import pytest

from case_intelligence.contracts import ArchiveDestination, TicketAction
from case_intelligence.isolation import AuthorizationError, Catalog, MatterAccess, MatterStateRegistry
from case_intelligence.lifecycle import ArchiveVerificationError, ClosureStage, ClosureStore, TrustedArchiveAdapter
from case_intelligence.tickets import TicketStore
from tests.support import ACTOR_ALPHA, ALPHA, NOW, matter, source


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def archive(destination_id: str = "archive-approved") -> ArchiveDestination:
    return ArchiveDestination(
        archive_destination_id=destination_id,
        display_name="Synthetic archive",
        policy_revision="policy-1",
    )


def advance_to_handoff(store: ClosureStore, run_id: str) -> None:
    for stage in (
        ClosureStage.EXPORTING,
        ClosureStage.VERIFYING_EXPORTS,
        ClosureStage.ARCHIVE_HANDOFF,
    ):
        store.advance(run_id, stage)


def complete(store: ClosureStore, run_id: str) -> None:
    for stage in (
        ClosureStage.DISABLING_ACCESS,
        ClosureStage.REMOVING_INDEXES,
        ClosureStage.PURGING_DERIVED_DATA,
        ClosureStage.COMPLETED,
    ):
        store.advance(run_id, stage)


def test_shared_state_fence_rejects_stale_catalog_ticket_and_lease_operations() -> None:
    clock = Clock()
    stale_active_matter = matter()
    registry = MatterStateRegistry([stale_active_matter])
    access = MatterAccess({ACTOR_ALPHA: {ALPHA}})
    catalog = Catalog(registry, [source()])
    serial = iter(range(1, 10))
    tickets = TicketStore(
        registry=registry,
        clock=clock,
        token_source=lambda size: next(serial).to_bytes(size, "big"),
    )
    closure = ClosureStore(registry=registry, clock=clock)

    pending = tickets.mint(
        access, ACTOR_ALPHA, ALPHA, TicketAction.OPEN_ORIGINAL, "version-alpha", 1
    )
    launch = tickets.mint(
        access, ACTOR_ALPHA, ALPHA, TicketAction.SAVE_ARTIFACT, "artifact-v1", 2
    )
    lease = tickets.redeem(
        launch.uri,
        access,
        ACTOR_ALPHA,
        ALPHA,
        TicketAction.SAVE_ARTIFACT,
        "artifact-v1",
        2,
        "helper-1",
    )

    closure.request(ALPHA, archive(), source_count=3, artifact_count=2)

    assert stale_active_matter.state.value == "active"
    assert registry.matter(ALPHA).state.value == "closing"
    with pytest.raises(AuthorizationError):
        catalog.search(access, ACTOR_ALPHA, ALPHA, "report")
    with pytest.raises(AuthorizationError):
        catalog.source_for_actor(access, ACTOR_ALPHA, ALPHA, "version-matter-alpha")
    with pytest.raises(PermissionError):
        tickets.redeem(
            pending.uri,
            access,
            ACTOR_ALPHA,
            ALPHA,
            TicketAction.OPEN_ORIGINAL,
            "version-alpha",
            1,
            "helper-1",
        )
    with pytest.raises(PermissionError):
        tickets.validate_lease(
            lease.lease_id,
            access,
            ACTOR_ALPHA,
            ALPHA,
            TicketAction.SAVE_ARTIFACT,
            "artifact-v1",
            2,
            "helper-1",
        )
    with pytest.raises(AuthorizationError):
        tickets.mint(
            access, ACTOR_ALPHA, ALPHA, TicketAction.OPEN_ORIGINAL, "version-alpha", 1
        )

    assert all(record.revoked_at == NOW for record in tickets.records)


def test_closure_rejects_receipt_for_unbound_archive_destination() -> None:
    clock = Clock()
    registry = MatterStateRegistry([matter()])
    store = ClosureStore(registry=registry, clock=clock)
    adapter = TrustedArchiveAdapter(clock=clock, attestation_key=b"synthetic-test-key")
    store.trust_adapter(adapter)
    run = store.request(ALPHA, archive(), source_count=3, artifact_count=2)
    advance_to_handoff(store, run.closure_run_id)

    mismatched = adapter.verify(
        ALPHA, run.closure_run_id, "archive-other", run.policy_revision
    )
    with pytest.raises(ArchiveVerificationError):
        store.verify_archive(run.closure_run_id, mismatched)


def test_completion_stores_one_immutable_closure_record() -> None:
    clock = Clock()
    registry = MatterStateRegistry([matter()])
    store = ClosureStore(registry=registry, clock=clock)
    adapter = TrustedArchiveAdapter(clock=clock, attestation_key=b"synthetic-test-key")
    store.trust_adapter(adapter)
    destination = archive()
    run = store.request(ALPHA, destination, source_count=3, artifact_count=2)
    advance_to_handoff(store, run.closure_run_id)
    store.verify_archive(
        run.closure_run_id,
        adapter.verify(
            ALPHA,
            run.closure_run_id,
            destination.archive_destination_id,
            destination.policy_revision,
        ),
    )

    clock.now += timedelta(minutes=5)
    complete(store, run.closure_run_id)
    first = store.closure_record(run.closure_run_id)
    clock.now += timedelta(days=1)
    second = store.closure_record(run.closure_run_id)

    assert second is first
    assert first.source_count == 3
    assert first.artifact_count == 2
    assert first.completed_at == NOW + timedelta(minutes=5)
