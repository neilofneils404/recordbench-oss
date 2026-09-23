from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from case_intelligence.source_locations import SourcePreflight, SourceScanItem
from case_intelligence.workspace_store import WorkspaceProblem, WorkspaceStore


FIXED = datetime(2026, 8, 28, 16, 0, tzinfo=timezone.utc)
ACTOR = "principal-synthetic-owner"


@pytest.fixture
def due_matter(tmp_path):
    now = [FIXED]
    path = tmp_path / "workbench.sqlite"
    primary = WorkspaceStore(path, clock=lambda: now[0])
    primary.upsert_principal(
        "test", "synthetic-owner", "Synthetic Owner", "synthetic-owner",
        preferred_principal_id=ACTOR,
    )
    matter = primary.create_matter("Synthetic retention race", "", ACTOR, retention_days=1)
    competing = WorkspaceStore(path, clock=lambda: now[0])
    # A deterministic interleaving should report contention immediately rather
    # than waiting for a writer held by this same test's other connection.
    competing.connection.execute("PRAGMA busy_timeout=0")
    now[0] += timedelta(days=9)
    try:
        yield primary, competing, matter, now
    finally:
        competing.close()
        primary.close()


def _queue_answer(store, matter):
    return store.queue_answer_job(
        matter.matter_id, None, ACTOR, "Summarize the synthetic record.",
        "answer-request-" + "a" * 32,
    )[0]


@pytest.mark.parametrize("work_kind", ["answer", "upload"])
def test_due_claim_serializes_active_work_inventory_with_other_connection(
    due_matter, monkeypatch, work_kind,
):
    primary, competing, matter, _ = due_matter
    admitted = []
    contended = []

    def admit_work():
        if work_kind == "answer":
            return _queue_answer(competing, matter)
        return competing.create_upload_session(
            matter.matter_id, ACTOR, "Synthetic upload",
            ({"display_name": "generated.txt", "relative_path": "generated.txt",
              "media_type": "text/plain", "expected_size": 9},),
        )

    original = primary._active_matter_work_counts_locked

    def inventory_then_admit(matter_id):
        counts = original(matter_id)
        try:
            admitted.append(admit_work())
        except sqlite3.OperationalError as exc:
            assert "locked" in str(exc)
            contended.append(True)
        return counts

    monkeypatch.setattr(primary, "_active_matter_work_counts_locked", inventory_then_admit)
    claimed = primary.begin_due_matter_purge(matter.matter_id, source_count=0)

    # Either admission wins and purge defers, or the purge transaction wins and
    # admission must fail after its lock is released. Both may never succeed.
    assert admitted or contended
    if admitted:
        assert claimed is None
        assert primary.matter_lifecycle(matter.matter_id).state == "active"
    else:
        assert claimed is not None
        assert claimed[1].state == "purging"
        with pytest.raises((KeyError, WorkspaceProblem)):
            admit_work()


def test_extension_cannot_report_success_after_other_connection_claims_purge(due_matter):
    primary, competing, matter, now = due_matter
    original = primary.matter_retention(matter.matter_id)
    claims = []
    errors = []

    def claim_before_writer_lock(statement):
        # SQLite invokes the trace before executing BEGIN. With an implicit
        # transaction this is after the extension's lifecycle read; with an
        # explicit transaction it is before the lifecycle read.
        if statement.strip().upper() != "BEGIN IMMEDIATE" or claims or errors:
            return
        try:
            claims.append(competing.begin_due_matter_purge(matter.matter_id, source_count=0))
        except Exception as exc:
            errors.append(exc)

    primary.connection.set_trace_callback(claim_before_writer_lock)
    try:
        with pytest.raises((KeyError, WorkspaceProblem)):
            primary.set_matter_retention(matter.matter_id, ACTOR, now[0] + timedelta(days=30))
    finally:
        primary.connection.set_trace_callback(None)

    assert not errors
    assert len(claims) == 1 and claims[0] is not None
    assert primary.matter_lifecycle(matter.matter_id).state == "purging"
    assert primary.matter_retention(matter.matter_id) == original


def test_extension_winning_before_due_claim_preserves_matter(due_matter):
    primary, competing, matter, now = due_matter
    assert len(primary.due_matter_retentions()) == 1
    extended = competing.set_matter_retention(
        matter.matter_id, ACTOR, now[0] + timedelta(days=365),
    )

    assert primary.begin_due_matter_purge(matter.matter_id, source_count=0) is None
    assert primary.matter_lifecycle(matter.matter_id).state == "active"
    assert primary.matter_retention(matter.matter_id) == extended


@pytest.mark.parametrize(
    "work_kind", ["ingest", "registered_ingest", "retry_ingest", "media", "media_summary", "analysis"],
)
def test_work_admission_cannot_cross_other_connection_purge_claim(due_matter, work_kind):
    primary, competing, matter, _ = due_matter
    claims = []
    errors = []
    if work_kind == "registered_ingest":
        plan = primary.create_ingest_plan(
            matter.matter_id,
            SourcePreflight(
                "synthetic-source", "Synthetic registered source", "",
                (SourceScanItem("generated.txt", "generated.txt", "text/plain", 9, 1, 1, 1),),
                0, 9,
            ),
        )
    elif work_kind == "retry_ingest":
        primary.queue_upload(matter.matter_id, "a" * 32)
        running = primary.claim_ingest_job("synthetic-ingest-worker")
        primary.finish_ingest_job(running.job_id, succeeded=False, message="Synthetic retry fixture.")
    elif work_kind == "media_summary":
        primary.queue_media_job(
            matter.matter_id, "a" * 32, "b" * 32, ACTOR,
            source_sha256="c" * 64, byte_size=100, media_type="audio/wav", duration_ms=1000,
        )
        media = primary.claim_media_job("synthetic-media-worker")
        transcript = primary.import_media_transcript(
            media.media_job_id,
            segments=({"external_segment_id": "synthetic-segment", "start_ms": 0,
                       "end_ms": 1000, "model_text": "Synthetic transcript."},),
            warnings=(), quality={}, provenance={},
        )
        primary.finish_media_job(media.media_job_id, degraded=False, message="Synthetic transcript ready.")
        primary.start_media_summary(transcript.transcript_id)
        primary.fail_media_summary(transcript.transcript_id, "Synthetic retry fixture.")

    def claim_before_writer_lock(statement):
        if statement.strip().upper() != "BEGIN IMMEDIATE" or claims or errors:
            return
        try:
            claims.append(competing.begin_due_matter_purge(matter.matter_id, source_count=0))
        except Exception as exc:
            errors.append(exc)

    primary.connection.set_trace_callback(claim_before_writer_lock)
    try:
        with pytest.raises((KeyError, WorkspaceProblem)):
            if work_kind == "ingest":
                primary.queue_upload(matter.matter_id, "a" * 32)
            elif work_kind == "registered_ingest":
                primary.confirm_ingest_plan(matter.matter_id, plan.plan_id, {1: "a" * 32}, ACTOR)
            elif work_kind == "retry_ingest":
                primary.retry_ingest_job(matter.matter_id, "a" * 32)
            elif work_kind == "media":
                primary.queue_media_job(
                    matter.matter_id, "a" * 32, "b" * 32, ACTOR,
                    source_sha256="c" * 64, byte_size=100, media_type="audio/wav", duration_ms=1000,
                )
            elif work_kind == "media_summary":
                primary.queue_media_summary(matter.matter_id, "a" * 32, "b" * 32, ACTOR)
            else:
                primary.start_analysis_run(matter.matter_id, ACTOR)
    finally:
        primary.connection.set_trace_callback(None)

    assert not errors
    assert len(claims) == 1 and claims[0] is not None
    assert primary.matter_lifecycle(matter.matter_id).state == "purging"
    assert not any(primary.active_matter_work_counts(matter.matter_id).values())


def test_due_purge_waits_for_worker_and_late_completion_cannot_recreate_content(due_matter):
    primary, competing, matter, _ = due_matter
    queued = _queue_answer(competing, matter)
    running = competing.claim_answer_job("synthetic-worker")
    assert running is not None and running.job_id == queued.job_id
    assert primary.begin_due_matter_purge(matter.matter_id, source_count=0) is None

    competing.fail_answer_job(running.job_id, "Synthetic worker stopped.")
    claimed = primary.begin_due_matter_purge(matter.matter_id, source_count=0)
    assert claimed is not None
    primary.complete_matter_purge(matter.matter_id, claimed[1].purge_id)

    with pytest.raises((KeyError, WorkspaceProblem)):
        competing.finish_answer_job(running.job_id, content="Synthetic late answer.", payload={})
    assert primary.matter_lifecycle(matter.matter_id).state == "deleted"
    assert primary.connection.execute(
        "SELECT COUNT(*) FROM workbench_answer_job WHERE matter_id=?", (matter.matter_id,),
    ).fetchone()[0] == 0
    assert primary.connection.execute(
        "SELECT COUNT(*) FROM workbench_conversation WHERE matter_id=?", (matter.matter_id,),
    ).fetchone()[0] == 0
