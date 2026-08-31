from __future__ import annotations

import pytest

from case_intelligence.jobs import JobService
from case_intelligence.sqlite_store import SQLiteStore
from tests.slice1_support import NOW, make_environment


def test_durable_jobs_strict_utf8_retry_idempotency_and_reopen(tmp_path):
    store, registry, inventory, _, roots = make_environment(tmp_path)
    inventory.inventory("matter-alpha", "location-alpha", "scan")
    jobs = JobService(store, registry, clock=lambda: NOW)
    job_id = jobs.run_next("matter-alpha")
    assert job_id is not None
    assert store.connection.execute("SELECT state FROM job WHERE job_id=?", (job_id,)).fetchone()[0] == "succeeded"
    assert store.connection.execute("SELECT count(*) FROM representation").fetchone()[0] == 1
    assert store.connection.execute("SELECT count(*) FROM segment").fetchone()[0] == 1
    assert jobs.run_next("matter-alpha") is None
    store.close()

    reopened = SQLiteStore(tmp_path / "catalog.sqlite")
    assert reopened.connection.execute("SELECT count(*) FROM segment").fetchone()[0] == 1
    assert reopened.connection.execute("SELECT count(*) FROM job_attempt").fetchone()[0] == 1
    reopened.close()


def test_failed_derive_is_durable_and_explicit_retry_does_not_duplicate(tmp_path):
    store, registry, inventory, _, roots = make_environment(tmp_path)
    inventory.inventory("matter-alpha", "location-alpha", "scan")
    report = roots["alpha"] / "nested/report.txt"
    original = report.read_bytes()
    report.write_bytes(b"\xffinvalid")
    jobs = JobService(store, registry, clock=lambda: NOW)
    with pytest.raises(ValueError):
        jobs.run_next("matter-alpha")
    job = store.connection.execute("SELECT job_id,state FROM job WHERE state='failed'").fetchone()
    assert job["state"] == "failed"
    report.write_bytes(original)
    jobs.retry("matter-alpha", job["job_id"])
    assert jobs.run_next("matter-alpha") == job["job_id"]
    assert store.connection.execute("SELECT count(*) FROM job_attempt WHERE job_id=?", (job["job_id"],)).fetchone()[0] == 2
    assert store.connection.execute("SELECT count(*) FROM segment").fetchone()[0] == 1
    store.close()


def test_unsupported_media_are_not_processed(tmp_path):
    store, _, inventory, _, _ = make_environment(tmp_path)
    inventory.inventory("matter-alpha", "location-alpha", "scan")
    assert store.connection.execute("SELECT count(*) FROM job WHERE state='not_processed'").fetchone()[0] == 2
    assert store.connection.execute("SELECT count(*) FROM job WHERE state='queued'").fetchone()[0] == 1
    store.close()
