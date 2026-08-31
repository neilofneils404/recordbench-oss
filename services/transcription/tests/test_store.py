from __future__ import annotations

import io
import multiprocessing
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from transcription_v2.domain import (  # noqa: E402
    ConcurrencyConflictError,
    IdentityMethod,
    IdentityStatus,
    InvalidTransitionError,
    JobStatus,
    NotFoundError,
    PipelineStage,
    RecordingType,
    RetryLimitError,
    SegmentDraft,
    StageStatus,
    TranscriptionOptions,
)
from transcription_v2.storage import FileStorage  # noqa: E402
from transcription_v2.store import SQLiteJobStore  # noqa: E402


OWNER_A = "opaque-owner-a"
OWNER_B = "opaque-owner-b"


def _claim_in_process(db_path: str, worker_id: str, start, results) -> None:
    try:
        store = SQLiteJobStore(db_path)
        if not start.wait(10):
            results.put((worker_id, None, "start timeout"))
            return
        claim = store.claim_next(worker_id)
        results.put((worker_id, claim.id if claim else None, None))
    except BaseException as exc:  # pragma: no cover - surfaced to parent assertion
        results.put((worker_id, None, f"{type(exc).__name__}: {exc}"))


class SQLiteJobStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary.name)
        self.db_path = self.temp_path / "state" / "jobs.sqlite3"
        self.store = SQLiteJobStore(self.db_path)
        self.storage = FileStorage(self.temp_path / "files", chunk_size=8)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_job_with_file(
        self,
        *,
        owner_key: str = OWNER_A,
        payload: bytes = b"safe synthetic media",
        options: TranscriptionOptions | None = None,
        max_attempts: int = 3,
        priority: int = 0,
    ):
        job = self.store.create_job(
            owner_key=owner_key,
            options=options,
            max_attempts=max_attempts,
            priority=priority,
        )
        ingested = self.storage.ingest_stream(
            job.id, io.BytesIO(payload), "recording.wav", media_type="audio/wav"
        )
        job_file = self.store.register_file(
            job.id,
            owner_key=owner_key,
            original_name=ingested.original_name,
            safe_name=ingested.safe_name,
            relative_path=ingested.relative_path,
            media_type=ingested.media_type,
            size_bytes=ingested.size_bytes,
            sha256=ingested.sha256,
        )
        return job, job_file, ingested

    def test_options_owner_scope_content_identity_and_queue(self) -> None:
        options = TranscriptionOptions(
            source_language="ES",
            translate_to_english=True,
            recording_type=RecordingType.MEETING,
            min_speakers=2,
            max_speakers=4,
            hotwords=("LANTERN-7",),
            glossary=("VX-204=synthetic asset code",),
            roster=("Speaker candidate A", "Speaker candidate B"),
            retention_hours=4,
        )
        job, job_file, _ = self.create_job_with_file(options=options)
        self.assertEqual(job.profile, "high_accuracy")
        self.assertEqual(job.options.source_language, "es")
        self.assertEqual(job.options.hotwords, ("LANTERN-7",))
        self.assertIsNone(job.expires_at)
        self.assertEqual(self.store.get_owned_job(job.id, OWNER_A).id, job.id)
        with self.assertRaises(NotFoundError):
            self.store.get_owned_job(job.id, OWNER_B)
        self.assertEqual([item.id for item in self.store.list_jobs(OWNER_A)], [job.id])
        self.assertEqual(self.store.list_jobs(OWNER_B), [])
        self.assertEqual(self.store.list_files(job.id, OWNER_A)[0].id, job_file.id)
        self.assertEqual(
            self.store.find_files_by_sha256(job_file.sha256, OWNER_A)[0].id,
            job_file.id,
        )
        self.assertEqual(self.store.find_files_by_sha256(job_file.sha256, OWNER_B), [])

        queued = self.store.enqueue_job(job.id, OWNER_A)
        self.assertEqual(queued.status, JobStatus.QUEUED)
        self.assertEqual(queued.stage, PipelineStage.PROBE)
        claimed = self.store.claim_next("worker-01")
        self.assertEqual(claimed.id, job.id)
        self.assertEqual(claimed.status, JobStatus.RUNNING)
        self.assertEqual(claimed.attempt, 1)
        self.assertEqual(claimed.worker_id, "worker-01")

    def test_retained_usage_is_owner_scoped_and_counts_registered_bytes(self) -> None:
        self.create_job_with_file(owner_key=OWNER_A, payload=b"aaa")
        self.create_job_with_file(owner_key=OWNER_A, payload=b"bbbb")
        self.create_job_with_file(owner_key=OWNER_B, payload=b"ccccc")

        self.assertEqual(self.store.retained_usage(OWNER_A), (2, 7))
        self.assertEqual(self.store.retained_usage(OWNER_B), (1, 5))
        self.assertEqual(self.store.retained_usage(), (3, 12))

    def test_atomic_claim_allows_exactly_one_process(self) -> None:
        job, _, _ = self.create_job_with_file()
        self.store.enqueue_job(job.id, OWNER_A)
        start_methods = multiprocessing.get_all_start_methods()
        context = multiprocessing.get_context("fork" if "fork" in start_methods else "spawn")
        start = context.Event()
        results = context.Queue()
        processes = [
            context.Process(
                target=_claim_in_process,
                args=(str(self.db_path), f"worker-{index}", start, results),
            )
            for index in range(4)
        ]
        for process in processes:
            process.start()
        start.set()
        observed = [results.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=15)
            if process.is_alive():  # pragma: no cover - defensive cleanup
                process.terminate()
                process.join(timeout=5)
            self.assertEqual(process.exitcode, 0)
        self.assertTrue(all(error is None for _, _, error in observed), observed)
        claimed_ids = [claimed_id for _, claimed_id, _ in observed if claimed_id]
        self.assertEqual(claimed_ids, [job.id])
        self.assertEqual(self.store.get_job(job.id).attempt, 1)

    def test_cancel_acknowledge_and_retry_semantics(self) -> None:
        job, _, _ = self.create_job_with_file(max_attempts=2)
        self.store.enqueue_job(job.id, OWNER_A)
        canceled = self.store.request_cancel(job.id, OWNER_A)
        self.assertEqual(canceled.status, JobStatus.CANCELED)
        self.assertIsNotNone(canceled.expires_at)

        retried = self.store.retry_job(job.id, OWNER_A)
        self.assertEqual(retried.status, JobStatus.QUEUED)
        self.assertIsNone(retried.expires_at)
        claimed = self.store.claim_next("worker-cancel")
        self.assertEqual(claimed.id, job.id)
        requested = self.store.request_cancel(job.id, OWNER_A)
        self.assertEqual(requested.status, JobStatus.CANCEL_REQUESTED)
        self.assertEqual(self.store.heartbeat(job.id, "worker-cancel").status, JobStatus.CANCEL_REQUESTED)
        acknowledged = self.store.acknowledge_cancel(job.id, "worker-cancel")
        self.assertEqual(acknowledged.status, JobStatus.CANCELED)
        self.assertIsNotNone(acknowledged.expires_at)

    def test_automatic_retry_stops_at_attempt_limit(self) -> None:
        job, _, _ = self.create_job_with_file(max_attempts=2)
        self.store.enqueue_job(job.id, OWNER_A)
        self.store.claim_next("worker-retry")
        requeued = self.store.fail_job(
            job.id,
            "worker-retry",
            "cuda_oom",
            retryable=True,
        )
        self.assertEqual(requeued.status, JobStatus.QUEUED)
        self.assertIsNone(requeued.expires_at)
        second = self.store.claim_next("worker-retry")
        self.assertEqual(second.attempt, 2)
        failed = self.store.fail_job(
            job.id,
            "worker-retry",
            "cuda_oom",
            retryable=True,
        )
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertEqual(failed.stage_status, StageStatus.FAILED)
        self.assertIsNotNone(failed.expires_at)
        with self.assertRaises(RetryLimitError):
            self.store.retry_job(job.id, OWNER_A)

    def test_restart_recovery_requeues_cancels_and_exhausts(self) -> None:
        retry_job, _, _ = self.create_job_with_file(max_attempts=2, priority=3)
        exhausted_job, _, _ = self.create_job_with_file(max_attempts=1, priority=2)
        cancel_job, _, _ = self.create_job_with_file(max_attempts=2, priority=1)
        for item in (retry_job, exhausted_job, cancel_job):
            self.store.enqueue_job(item.id, OWNER_A)

        self.store.claim_next("worker-stale-1")
        self.store.claim_next("worker-stale-2")
        self.store.claim_next("worker-stale-3")
        self.store.request_cancel(cancel_job.id, OWNER_A)
        summary = self.store.recover_running_jobs(
            stale_before=datetime.now(timezone.utc) + timedelta(seconds=1)
        )
        self.assertEqual(summary.requeued, 1)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.canceled, 1)
        self.assertEqual(self.store.get_job(retry_job.id).status, JobStatus.QUEUED)
        self.assertEqual(self.store.get_job(exhausted_job.id).status, JobStatus.FAILED)
        self.assertEqual(self.store.get_job(cancel_job.id).status, JobStatus.CANCELED)

    def test_segments_optimistic_edit_overlap_and_speaker_mapping(self) -> None:
        job, job_file, _ = self.create_job_with_file()
        self.store.enqueue_job(job.id, OWNER_A)
        self.store.claim_next("worker-segments")
        created = self.store.add_segments(
            job.id,
            job_file.id,
            "worker-segments",
            [
                SegmentDraft(
                    ordinal=0,
                    start_ms=100,
                    end_ms=900,
                    model_text="ULTRA_SECRET_MODEL_TEXT",
                    speaker_key="SPEAKER_00",
                    confidence=0.81,
                    overlap=True,
                ),
                SegmentDraft(
                    ordinal=1,
                    start_ms=900,
                    end_ms=1400,
                    model_text="second segment",
                ),
            ],
        )
        self.assertTrue(created[0].overlap)
        self.assertEqual(created[0].text, "ULTRA_SECRET_MODEL_TEXT")
        edited = self.store.update_segment(
            created[0].id,
            OWNER_A,
            expected_revision=1,
            edited_text="reviewed wording",
            speaker_key="SPEAKER_01",
            overlap=False,
        )
        self.assertEqual(edited.revision, 2)
        self.assertEqual(edited.model_text, "ULTRA_SECRET_MODEL_TEXT")
        self.assertEqual(edited.text, "reviewed wording")
        self.assertFalse(edited.overlap)
        with self.assertRaises(ConcurrencyConflictError):
            self.store.update_segment(
                created[0].id,
                OWNER_A,
                expected_revision=1,
                edited_text="stale edit",
            )
        with self.assertRaises(NotFoundError):
            self.store.list_segments(job.id, OWNER_B)

        mapping = self.store.set_speaker_mapping(
            job.id,
            OWNER_A,
            "SPEAKER_01",
            "Confirmed Person",
            identity_status=IdentityStatus.CONFIRMED,
            identity_method=IdentityMethod.MANUAL,
            confidence=1.0,
            expected_revision=0,
        )
        self.assertEqual(mapping.revision, 1)
        updated_mapping = self.store.set_speaker_mapping(
            job.id,
            OWNER_A,
            "SPEAKER_01",
            "Confirmed Person",
            identity_status=IdentityStatus.CONFIRMED,
            identity_method=IdentityMethod.MANUAL,
            confidence=1.0,
            expected_revision=1,
        )
        self.assertEqual(updated_mapping.revision, 2)
        with self.assertRaises(ConcurrencyConflictError):
            self.store.set_speaker_mapping(
                job.id,
                OWNER_A,
                "SPEAKER_01",
                "Stale Person",
                expected_revision=1,
            )
        self.assertEqual(len(self.store.list_speaker_mappings(job.id, OWNER_A)), 1)

        # Audit events expose only codes/state, never transcript content or identities.
        events = self.store.list_events(job.id, OWNER_A)
        event_rendering = "\n".join(repr(event) for event in events)
        self.assertNotIn("ULTRA_SECRET_MODEL_TEXT", event_rendering)
        self.assertNotIn("reviewed wording", event_rendering)
        self.assertNotIn("Confirmed Person", event_rendering)
        with sqlite3.connect(self.db_path) as connection:
            event_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(job_events)")
            }
        self.assertFalse(
            {"message", "payload", "details", "text", "filename"} & event_columns
        )

    def test_success_starts_delivery_ttl_not_upload_time(self) -> None:
        options = TranscriptionOptions(retention_hours=4)
        job, _, _ = self.create_job_with_file(options=options)
        self.assertIsNone(job.expires_at)
        self.store.enqueue_job(job.id, OWNER_A)
        self.store.claim_next("worker-success")
        self.store.set_stage(
            job.id,
            "worker-success",
            PipelineStage.EXPORT,
            StageStatus.SUCCEEDED,
        )
        before = datetime.now(timezone.utc)
        succeeded = self.store.complete_job(job.id, "worker-success")
        expiry = datetime.fromisoformat(succeeded.expires_at)
        self.assertEqual(succeeded.status, JobStatus.SUCCEEDED)
        self.assertGreaterEqual(expiry, before + timedelta(hours=3, minutes=59))
        self.assertLessEqual(expiry, before + timedelta(hours=4, minutes=1))

    def test_worker_replace_segments_is_atomic_and_discards_stale_edits(self) -> None:
        job, job_file, _ = self.create_job_with_file()
        self.store.enqueue_job(job.id, OWNER_A)
        self.store.claim_next("worker-rerun")
        original = self.store.add_segment(
            job.id,
            job_file.id,
            "worker-rerun",
            SegmentDraft(0, 0, 1000, "first model draft"),
        )
        edited = self.store.update_segment(
            original.id,
            OWNER_A,
            expected_revision=1,
            edited_text="human correction tied to first draft",
        )
        self.assertEqual(edited.revision, 2)

        with self.assertRaises(ConcurrencyConflictError):
            self.store.replace_segments(
                job.id,
                job_file.id,
                "wrong-worker",
                [SegmentDraft(0, 0, 500, "unauthorized replacement")],
            )

        # Force an insert-time primary-key collision after DELETE. The SQLite
        # transaction must roll back and restore the prior human-edited draft.
        with patch("transcription_v2.store.uuid.uuid4") as mocked_uuid:
            mocked_uuid.return_value.hex = "sameid"
            with self.assertRaises(ConcurrencyConflictError):
                self.store.replace_segments(
                    job.id,
                    job_file.id,
                    "worker-rerun",
                    [
                        SegmentDraft(0, 0, 400, "failed replacement one"),
                        SegmentDraft(1, 400, 800, "failed replacement two"),
                    ],
                )
        after_rollback = self.store.list_segments(job.id, OWNER_A)
        self.assertEqual(len(after_rollback), 1)
        self.assertEqual(after_rollback[0].id, original.id)
        self.assertEqual(after_rollback[0].text, "human correction tied to first draft")

        replacement = self.store.replace_segments(
            job.id,
            job_file.id,
            "worker-rerun",
            [SegmentDraft(0, 0, 800, "second model draft", overlap=True)],
        )
        self.assertEqual(len(replacement), 1)
        self.assertNotEqual(replacement[0].id, original.id)
        self.assertEqual(replacement[0].model_text, "second model draft")
        self.assertIsNone(replacement[0].edited_text)
        self.assertEqual(replacement[0].revision, 1)
        self.assertTrue(replacement[0].overlap)

    def test_hard_delete_cascades_content_events_and_files(self) -> None:
        job, job_file, ingested = self.create_job_with_file()
        self.store.enqueue_job(job.id, OWNER_A)
        self.store.claim_next("worker-delete")
        segment = self.store.add_segment(
            job.id,
            job_file.id,
            "worker-delete",
            SegmentDraft(0, 0, 1000, "content to purge", speaker_key="SPEAKER_00"),
        )
        self.store.set_speaker_mapping(
            job.id,
            OWNER_A,
            "SPEAKER_00",
            "Name to purge",
            identity_status=IdentityStatus.SUGGESTED,
            identity_method=IdentityMethod.CONTEXT,
        )
        self.store.fail_job(job.id, "worker-delete", "test_failure")
        self.assertTrue(ingested.absolute_path.exists())
        self.assertTrue(
            self.store.delete_job(
                job.id,
                OWNER_A,
                delete_files=self.storage.delete_job_tree,
            )
        )
        self.assertFalse(ingested.absolute_path.exists())
        with self.assertRaises(NotFoundError):
            self.store.get_job(job.id)
        with sqlite3.connect(self.db_path) as connection:
            for table in (
                "jobs",
                "job_files",
                "job_events",
                "segments",
                "speaker_mappings",
            ):
                count = connection.execute(
                    f"SELECT count(*) FROM {table}"
                ).fetchone()[0]
                self.assertEqual(count, 0, table)
        self.assertIsNotNone(segment.id)

    def test_purge_expired_hard_deletes_database_and_job_tree(self) -> None:
        job, _, ingested = self.create_job_with_file(
            options=TranscriptionOptions(retention_hours=1)
        )
        self.store.enqueue_job(job.id, OWNER_A)
        self.store.claim_next("worker-expiry")
        self.store.set_stage(
            job.id,
            "worker-expiry",
            PipelineStage.EXPORT,
            StageStatus.SUCCEEDED,
        )
        succeeded = self.store.complete_job(job.id, "worker-expiry")
        future = datetime.fromisoformat(succeeded.expires_at) + timedelta(seconds=1)
        deleted = self.store.purge_expired(
            now=future,
            delete_files=self.storage.delete_job_tree,
        )
        self.assertEqual(deleted, [job.id])
        self.assertFalse(ingested.absolute_path.exists())
        with self.assertRaises(NotFoundError):
            self.store.get_job(job.id)

    def test_stale_unfinished_upload_is_unclaimable_before_file_deletion(self) -> None:
        job, _, ingested = self.create_job_with_file()
        self.store.enqueue_job(job.id, OWNER_A)
        claim_during_delete = []

        def delete_files(job_id: str) -> None:
            claim_during_delete.append(self.store.claim_next("too-late-worker"))
            self.storage.delete_job_tree(job_id)

        deleted = self.store.purge_stale_unfinished(
            stale_before=datetime.now(timezone.utc) + timedelta(seconds=1),
            delete_files=delete_files,
        )
        self.assertEqual(deleted, [job.id])
        self.assertEqual(claim_during_delete, [None])
        self.assertFalse(ingested.absolute_path.exists())
        with self.assertRaises(NotFoundError):
            self.store.get_job(job.id)

    def test_stale_unfinished_purge_never_selects_running_job(self) -> None:
        job, _, ingested = self.create_job_with_file()
        self.store.enqueue_job(job.id, OWNER_A)
        self.store.claim_next("active-worker")
        deleted = self.store.purge_stale_unfinished(
            stale_before=datetime.now(timezone.utc) + timedelta(days=1),
            delete_files=self.storage.delete_job_tree,
        )
        self.assertEqual(deleted, [])
        self.assertTrue(ingested.absolute_path.exists())

    def test_batch_retention_waits_for_final_terminal_and_survives_restart(self) -> None:
        batch_id = "batch_11111111111111111111111111111111"
        options = TranscriptionOptions(retention_hours=4, batch_id=batch_id)
        first, _, first_ingested = self.create_job_with_file(
            payload=b"batch-first", options=options
        )
        second, _, second_ingested = self.create_job_with_file(
            payload=b"batch-second", options=options
        )
        self.store.enqueue_job(first.id, OWNER_A)
        self.store.enqueue_job(second.id, OWNER_A)

        claimed_first = self.store.claim_next("batch-worker-first")
        self.assertEqual(first.id, claimed_first.id)
        self.store.set_stage(
            first.id,
            "batch-worker-first",
            PipelineStage.EXPORT,
            StageStatus.SUCCEEDED,
        )
        early = self.store.complete_job(first.id, "batch-worker-first")
        self.assertIsNone(early.expires_at)

        claimed_second = self.store.claim_next("batch-worker-second")
        self.assertEqual(second.id, claimed_second.id)
        artificial_past = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat(timespec="microseconds")
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE jobs SET expires_at = ? WHERE id = ?",
                (artificial_past, first.id),
            )

        restarted = SQLiteJobStore(self.db_path)
        self.assertIsNone(restarted.get_job(first.id).expires_at)
        self.assertEqual(
            [],
            restarted.purge_expired(
                now=datetime.now(timezone.utc),
                delete_files=self.storage.delete_job_tree,
            ),
        )
        self.assertTrue(first_ingested.absolute_path.exists())

        restarted.set_stage(
            second.id,
            "batch-worker-second",
            PipelineStage.EXPORT,
            StageStatus.SUCCEEDED,
        )
        final = restarted.complete_job(second.id, "batch-worker-second")
        first_after = restarted.get_job(first.id)
        self.assertEqual(first_after.expires_at, final.expires_at)
        expected_expiry = datetime.fromisoformat(final.finished_at) + timedelta(hours=4)
        self.assertEqual(expected_expiry, datetime.fromisoformat(final.expires_at))

        deleted = restarted.purge_expired(
            now=expected_expiry + timedelta(seconds=1),
            delete_files=self.storage.delete_job_tree,
        )
        self.assertEqual({first.id, second.id}, set(deleted))
        self.assertFalse(first_ingested.absolute_path.exists())
        self.assertFalse(second_ingested.absolute_path.exists())

    def test_early_failed_batch_member_cannot_expire_while_sibling_runs(self) -> None:
        batch_id = "batch_22222222222222222222222222222222"
        options = TranscriptionOptions(retention_hours=4, batch_id=batch_id)
        first, _, first_ingested = self.create_job_with_file(
            payload=b"failed-first", options=options
        )
        second, _, _ = self.create_job_with_file(
            payload=b"running-second", options=options
        )
        self.store.enqueue_job(first.id, OWNER_A)
        self.store.enqueue_job(second.id, OWNER_A)
        self.store.claim_next("failed-batch-worker")
        early_failed = self.store.fail_job(
            first.id, "failed-batch-worker", "synthetic_failure"
        )
        self.assertEqual(JobStatus.FAILED, early_failed.status)
        self.assertIsNone(early_failed.expires_at)
        self.store.claim_next("running-batch-worker")

        artificial_past = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat(timespec="microseconds")
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE jobs SET expires_at = ? WHERE id = ?",
                (artificial_past, first.id),
            )
        self.assertEqual(
            [],
            self.store.purge_expired(
                now=datetime.now(timezone.utc),
                delete_files=self.storage.delete_job_tree,
            ),
        )
        self.assertIsNone(self.store.get_job(first.id).expires_at)
        self.assertTrue(first_ingested.absolute_path.exists())

        final_failed = self.store.fail_job(
            second.id, "running-batch-worker", "synthetic_failure"
        )
        first_after = self.store.get_job(first.id)
        self.assertEqual(first_after.expires_at, final_failed.expires_at)
        self.assertEqual(
            datetime.fromisoformat(final_failed.finished_at) + timedelta(hours=4),
            datetime.fromisoformat(final_failed.expires_at),
        )

    def test_retry_preserves_batch_membership_and_restarts_shared_retention(self) -> None:
        batch_id = "batch_33333333333333333333333333333333"
        options = TranscriptionOptions(retention_hours=4, batch_id=batch_id)
        first, _, _ = self.create_job_with_file(payload=b"retry-first", options=options)
        second, _, _ = self.create_job_with_file(payload=b"success-second", options=options)
        self.store.enqueue_job(first.id, OWNER_A)
        self.store.enqueue_job(second.id, OWNER_A)
        self.store.claim_next("retry-worker-first")
        self.store.fail_job(first.id, "retry-worker-first", "synthetic_failure")
        self.store.claim_next("retry-worker-second")
        self.store.set_stage(
            second.id,
            "retry-worker-second",
            PipelineStage.EXPORT,
            StageStatus.SUCCEEDED,
        )
        self.store.complete_job(second.id, "retry-worker-second")
        original_expiry = self.store.get_job(first.id).expires_at
        self.assertEqual(original_expiry, self.store.get_job(second.id).expires_at)
        terminal_snapshot = self.store.batch_state_snapshot(second.id, OWNER_A)

        retried = self.store.retry_job(first.id, OWNER_A)
        self.assertEqual(first.id, retried.id)
        self.assertEqual(batch_id, retried.options.batch_id)
        self.assertIsNone(retried.expires_at)
        self.assertIsNone(self.store.get_job(second.id).expires_at)
        members = [
            job for job in self.store.list_jobs(OWNER_A) if job.options.batch_id == batch_id
        ]
        self.assertEqual({first.id, second.id}, {job.id for job in members})
        deletion_calls: list[str] = []
        self.assertFalse(
            self.store.delete_batch_if_unchanged(
                second.id,
                OWNER_A,
                terminal_snapshot,
                delete_files=deletion_calls.append,
            )
        )
        self.assertEqual([], deletion_calls)

        claimed_retry = self.store.claim_next("retry-worker-final")
        self.assertEqual(first.id, claimed_retry.id)
        self.store.set_stage(
            first.id,
            "retry-worker-final",
            PipelineStage.EXPORT,
            StageStatus.SUCCEEDED,
        )
        final = self.store.complete_job(first.id, "retry-worker-final")
        self.assertEqual(final.expires_at, self.store.get_job(second.id).expires_at)
        self.assertGreaterEqual(
            datetime.fromisoformat(final.expires_at),
            datetime.fromisoformat(original_expiry),
        )
        self.assertEqual(2, final.attempt)

    def test_failed_batch_cleanup_reservation_retries_without_extending_ttl(self) -> None:
        batch_id = "batch_44444444444444444444444444444444"
        options = TranscriptionOptions(retention_hours=4, batch_id=batch_id)
        first, _, first_ingested = self.create_job_with_file(
            payload=b"cleanup-first", options=options
        )
        second, _, second_ingested = self.create_job_with_file(
            payload=b"cleanup-second", options=options
        )
        for index, job in enumerate((first, second)):
            self.store.enqueue_job(job.id, OWNER_A)
            worker = f"cleanup-worker-{index}"
            self.store.claim_next(worker)
            self.store.set_stage(
                job.id, worker, PipelineStage.EXPORT, StageStatus.SUCCEEDED
            )
            self.store.complete_job(job.id, worker)
        expiry = datetime.fromisoformat(self.store.get_job(first.id).expires_at)
        calls = 0

        def fail_second_delete(job_id: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic cleanup failure")
            self.storage.delete_job_tree(job_id)

        with self.assertRaisesRegex(OSError, "synthetic cleanup failure"):
            self.store.purge_expired(
                now=expiry + timedelta(seconds=1),
                delete_files=fail_second_delete,
            )
        reserved_first = self.store.get_job(first.id)
        reserved_second = self.store.get_job(second.id)
        self.assertEqual("retention_expired", reserved_first.error_code)
        self.assertEqual(reserved_first.expires_at, reserved_second.expires_at)
        self.assertLessEqual(
            datetime.fromisoformat(reserved_first.expires_at),
            expiry + timedelta(seconds=1),
        )

        deleted = self.store.purge_expired(
            now=expiry + timedelta(seconds=2),
            delete_files=self.storage.delete_job_tree,
        )
        self.assertEqual({first.id, second.id}, set(deleted))
        self.assertFalse(first_ingested.absolute_path.exists())
        self.assertFalse(second_ingested.absolute_path.exists())

    def test_stale_unfinished_cleanup_protects_running_sibling_then_deletes_batch(self) -> None:
        batch_id = "batch_55555555555555555555555555555555"
        options = TranscriptionOptions(batch_id=batch_id)
        first, _, first_ingested = self.create_job_with_file(
            payload=b"stale-running", options=options
        )
        second, _, second_ingested = self.create_job_with_file(
            payload=b"stale-queued", options=options
        )
        self.store.enqueue_job(first.id, OWNER_A)
        self.store.enqueue_job(second.id, OWNER_A)
        self.store.claim_next("stale-batch-worker")
        future = datetime.now(timezone.utc) + timedelta(days=3)

        self.assertEqual(
            [],
            self.store.purge_stale_unfinished(
                stale_before=future,
                delete_files=self.storage.delete_job_tree,
            ),
        )
        self.assertTrue(first_ingested.absolute_path.exists())
        self.assertTrue(second_ingested.absolute_path.exists())

        self.store.fail_job(first.id, "stale-batch-worker", "synthetic_failure")
        deleted = self.store.purge_stale_unfinished(
            stale_before=future,
            delete_files=self.storage.delete_job_tree,
        )
        self.assertEqual({first.id, second.id}, set(deleted))
        self.assertFalse(first_ingested.absolute_path.exists())
        self.assertFalse(second_ingested.absolute_path.exists())

    def test_conditional_batch_purge_rejects_edit_after_deletion_reservation(self) -> None:
        batch_id = "batch_66666666666666666666666666666666"
        options = TranscriptionOptions(batch_id=batch_id)
        first, first_file, _ = self.create_job_with_file(
            payload=b"reserved-edit-first", options=options
        )
        second, _, _ = self.create_job_with_file(
            payload=b"reserved-edit-second", options=options
        )
        segment = None
        for index, job in enumerate((first, second)):
            self.store.enqueue_job(job.id, OWNER_A)
            worker = f"reserved-edit-worker-{index}"
            self.store.claim_next(worker)
            if index == 0:
                segment = self.store.add_segment(
                    first.id,
                    first_file.id,
                    worker,
                    SegmentDraft(0, 0, 1000, "immutable machine text"),
                )
            self.store.set_stage(
                job.id, worker, PipelineStage.EXPORT, StageStatus.SUCCEEDED
            )
            self.store.complete_job(job.id, worker)
        self.assertIsNotNone(segment)
        snapshot = self.store.batch_state_snapshot(first.id, OWNER_A)
        rejected_edit = False

        def delete_with_racing_edit(job_id: str) -> None:
            nonlocal rejected_edit
            if not rejected_edit:
                with self.assertRaises(InvalidTransitionError):
                    self.store.update_segment(
                        segment.id,
                        OWNER_A,
                        expected_revision=segment.revision,
                        edited_text="must not survive deletion reservation",
                    )
                rejected_edit = True
            self.storage.delete_job_tree(job_id)

        self.assertTrue(
            self.store.delete_batch_if_unchanged(
                first.id,
                OWNER_A,
                snapshot,
                delete_files=delete_with_racing_edit,
            )
        )
        self.assertTrue(rejected_edit)
        with self.assertRaises(NotFoundError):
            self.store.get_job(first.id)
        with self.assertRaises(NotFoundError):
            self.store.get_job(second.id)

    def test_invalid_transitions_are_rejected(self) -> None:
        job, _, _ = self.create_job_with_file()
        with self.assertRaises(ConcurrencyConflictError):
            self.store.complete_job(job.id, "unowned-worker")
        self.store.enqueue_job(job.id, OWNER_A)
        self.store.claim_next("worker-stage")
        self.store.set_stage(
            job.id,
            "worker-stage",
            PipelineStage.TRANSCRIBE,
            StageStatus.RUNNING,
        )
        with self.assertRaises(InvalidTransitionError):
            self.store.set_stage(
                job.id,
                "worker-stage",
                PipelineStage.PROBE,
                StageStatus.RUNNING,
            )


if __name__ == "__main__":
    unittest.main()
