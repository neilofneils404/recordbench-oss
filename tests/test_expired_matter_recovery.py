"""Synthetic stopped-runtime recovery; no encrypted-backup or model-quality claim."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import threading
import zipfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from case_intelligence.answer_context import AnswerContextRepository
from case_intelligence.matter_context import MatterContextService
from case_intelligence.workbench import CaseIntelligenceWorkbench, MatterMaintenanceCoordinator
from case_intelligence.workspace_store import WorkspaceStore
from tests.test_answer_context import case, execute, submit
from tests.test_assertion_workflow import _app
from tests.test_evidence_graph_workflow import connections
from tests.test_matter_notebook import WEB_ACTOR


@pytest.fixture(autouse=True)
def held_maintenance(monkeypatch):
    # A recovered due schedule must be inspected before the first maintenance run.
    monkeypatch.setenv("CASE_INTELLIGENCE_MAINTENANCE_ENABLED", "0")


def _tree_digests(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _sources(bench, matter):
    store = bench.source_store(matter)
    return {
        identifier: (
            document.version_id,
            document.digest,
            hashlib.sha256(store.source_path(identifier, verify_digest=True).read_bytes()).hexdigest(),
        )
        for identifier, document in store.documents.items()
    }


def _assert_sqlite_integrity(runtime, *, source_registry_present=True):
    databases = [path for path in runtime.rglob("*") if path.suffix in {".sqlite", ".sqlite3"}]
    assert len(databases) == (2 if source_registry_present else 1)
    for path in databases:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.fixture
def stopped_recovery_snapshot(case, tmp_path):
    bench, matter = case["bench"], case["matter"]
    created = bench.workspace.current_time()
    original_retention = bench.workspace.set_matter_retention(
        matter.matter_id, WEB_ACTOR, created + timedelta(days=30)
    )
    assert submit(case).status_code == 202
    job, result, _ = execute(case)
    assert result.verified_answer.answerable
    receipt = AnswerContextRepository(bench.workspace).receipt(matter.matter_id, job.job_id)
    selection = case["service"].repository.export(matter.matter_id)
    sources = _sources(bench, matter)
    assert len(selection["selections"][0]["entries"]) == 4
    assert len(receipt["attempts"]) >= 2
    assert all(attempt["state"] == "completed" for attempt in receipt["attempts"])
    assert not any(bench.matter_active_work_counts(matter.matter_id).values())

    # No writer is left open when the entire runtime (not just its control DB)
    # is captured. Only this synthetic temporary original is removed.
    runtime = bench.runtime_dir
    source_root = bench.source_store(matter).root.relative_to(runtime)
    # An operator-retained original outside managed storage is not a purge target.
    external_original = tmp_path / "operator-retained-original.txt"
    source_store = bench.source_store(matter)
    external_bytes = source_store.source_path(next(iter(sources))).read_bytes()
    external_original.write_bytes(external_bytes)
    bench.close()
    backup, restored = tmp_path / "stopped-backup", tmp_path / "isolated-restore"
    original_files = _tree_digests(runtime)
    shutil.copytree(runtime, backup)
    assert _tree_digests(backup) == original_files
    shutil.rmtree(runtime)
    assert not runtime.exists()
    shutil.copytree(backup, restored)
    assert _tree_digests(restored) == original_files
    _assert_sqlite_integrity(restored)
    return dict(
        matter=matter, job=job, receipt=receipt, selection=selection, sources=sources,
        original_retention=original_retention, recovery_now=created + timedelta(days=38),
        runtime=runtime, backup=backup, restored=restored, original_files=original_files,
        source_root=source_root, external_original=external_original, external_bytes=external_bytes,
    )


def _set_clock_before_startup(monkeypatch, recovery_now):
    original_init = WorkspaceStore.__init__

    def recovered_store_init(self, *args, **kwargs):
        # Use the production constructor's existing clock injection before any
        # startup recovery or maintenance can inspect the restored schedule.
        kwargs["clock"] = lambda: recovery_now
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(WorkspaceStore, "__init__", recovered_store_init)


def _assert_snapshot_and_external_original_unchanged(snapshot):
    assert _tree_digests(snapshot["backup"]) == snapshot["original_files"]
    assert not snapshot["runtime"].exists()
    assert snapshot["external_original"].read_bytes() == snapshot["external_bytes"]


@pytest.mark.parametrize("extend_before_activation", [False, True], ids=["due-is-purged", "renewed-is-preserved"])
def test_expired_complete_restore_is_inspected_before_maintenance(stopped_recovery_snapshot, monkeypatch, extend_before_activation):
    """Restore does not reset expiry; renewal is a separate owner decision."""
    snapshot = stopped_recovery_snapshot
    matter, job = snapshot["matter"], snapshot["job"]
    receipt, selection, sources = snapshot["receipt"], snapshot["selection"], snapshot["sources"]
    restored, recovery_now = snapshot["restored"], snapshot["recovery_now"]
    _set_clock_before_startup(monkeypatch, recovery_now)

    with TestClient(_app(restored)) as client:
        recovered = client.app.state.workbench
        assert recovered.workspace.current_time() == recovery_now
        assert client.get("/health").json()["maintenance"]["enabled"] is False
        assert recovered.maintenance is None
        assert recovered.workspace.matter_retention(matter.matter_id) == snapshot["original_retention"]
        assert recovered.retention_projection(matter)["status"] == "due"
        assert recovered.workspace.matter_lifecycle(matter.matter_id).state == "active"
        assert _sources(recovered, matter) == sources

        recovered_selection = MatterContextService(recovered.assertion_service(matter))
        assert recovered_selection.repository.export(matter.matter_id) == selection
        current, _ = recovered_selection.inspect(matter.matter_id, WEB_ACTOR)
        assert all(row["state"] == "Unchanged" for row in current["rows"])
        detail = client.get(f"/matters/{matter.slug}/answer-jobs/{job.job_id}/context?format=json")
        assert detail.status_code == 200, detail.text
        assert detail.json()["snapshot"] == receipt["snapshot"]
        assert detail.json()["attempts"] == receipt["attempts"]
        for record in receipt["snapshot"]["records"]:
            for reference in record["references"]:
                assert client.get(f"/matters/{matter.slug}", params={"support": reference["support_token"]}).status_code == 200
        bundle = client.get(f"/matters/{matter.slug}/export")
        assert bundle.status_code == 200, bundle.text
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            assert json.loads(archive.read("context/selections.json")) == selection
            exported_receipt = json.loads(archive.read(f"context/{job.job_id}.json"))
            assert exported_receipt["snapshot"] == receipt["snapshot"]
            assert exported_receipt["attempts"] == receipt["attempts"]

        if extend_before_activation:
            expires_on = (recovery_now + timedelta(days=30)).date().isoformat()
            response = client.post(
                f"/matters/{matter.slug}/retention",
                data={"expires_on": expires_on}, follow_redirects=False,
            )
            assert response.status_code == 303 and "error=" not in response.headers["location"]
            renewed = recovered.workspace.matter_retention(matter.matter_id)
            assert renewed.scheduled_by == WEB_ACTOR
            assert renewed != snapshot["original_retention"]
            assert recovered.retention_projection(matter)["expires_on"] == expires_on

        # Activate the production coordinator explicitly only after inspection.
        # Its first pass runs immediately, even with a fifteen-minute interval.
        completed = threading.Event()
        outcome = {}

        def maintenance_pass():
            try:
                outcome.update(recovered.run_maintenance_once())
                return outcome
            finally:
                completed.set()

        recovered.maintenance = MatterMaintenanceCoordinator(maintenance_pass, interval_seconds=900)
        assert completed.wait(10), "The first maintenance pass did not complete."
        recovered.maintenance.close()
        assert outcome == {
            "uploads_cleaned": 0,
            "matters_purged": 0 if extend_before_activation else 1,
            "matters_deferred": 0,
        }
        if extend_before_activation:
            assert recovered.workspace.matter_lifecycle(matter.matter_id).state == "active"
            assert _sources(recovered, matter) == sources
            assert recovered_selection.repository.export(matter.matter_id) == selection
            assert AnswerContextRepository(recovered.workspace).receipt(matter.matter_id, job.job_id) == receipt
            assert client.get(f"/matters/{matter.slug}/export").status_code == 200
        else:
            assert recovered.workspace.matter_lifecycle(matter.matter_id).state == "deleted"
            assert not (restored / snapshot["source_root"]).exists()
            for table in (
                "workbench_context_selection", "workbench_context_entry",
                "workbench_answer_context", "workbench_answer_context_attempt",
            ):
                assert recovered.workspace.connection.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
            assert client.get(f"/matters/{matter.slug}/answer-jobs/{job.job_id}/context?format=json").status_code == 404
        _assert_sqlite_integrity(restored, source_registry_present=extend_before_activation)

    # Maintenance and the separate owner decision never modify the held backup.
    _assert_snapshot_and_external_original_unchanged(snapshot)


def test_enabled_startup_immediately_purges_expired_complete_restore(stopped_recovery_snapshot, monkeypatch):
    """The configured interval is not an inspection window after app startup."""
    snapshot = stopped_recovery_snapshot
    matter, job = snapshot["matter"], snapshot["job"]
    _set_clock_before_startup(monkeypatch, snapshot["recovery_now"])
    monkeypatch.setenv("CASE_INTELLIGENCE_MAINTENANCE_ENABLED", "1")
    monkeypatch.setenv("CASE_INTELLIGENCE_MAINTENANCE_INTERVAL_SECONDS", "86400")
    completed = threading.Event()
    observed = {}
    original_run = CaseIntelligenceWorkbench.run_maintenance_once

    def observed_run(self):
        try:
            observed["due_at_startup"] = self.workspace.due_matter_retentions()
            observed["result"] = original_run(self)
            return observed["result"]
        finally:
            completed.set()

    monkeypatch.setattr(CaseIntelligenceWorkbench, "run_maintenance_once", observed_run)
    with TestClient(_app(snapshot["restored"])) as client:
        recovered = client.app.state.workbench
        assert recovered.maintenance is not None
        assert completed.wait(10), "Enabled startup did not run maintenance immediately."
        recovered.maintenance.close()
        assert observed["due_at_startup"] == (snapshot["original_retention"],)
        assert observed["result"] == {
            "uploads_cleaned": 0, "matters_purged": 1, "matters_deferred": 0,
        }
        assert client.get("/health").json()["maintenance"]["enabled"] is True
        assert recovered.workspace.matter_lifecycle(matter.matter_id).state == "deleted"
        assert not (snapshot["restored"] / snapshot["source_root"]).exists()
        for table in (
            "workbench_context_selection", "workbench_context_entry",
            "workbench_answer_context", "workbench_answer_context_attempt",
        ):
            assert recovered.workspace.connection.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
        assert client.get(f"/matters/{matter.slug}/answer-jobs/{job.job_id}/context?format=json").status_code == 404
        _assert_sqlite_integrity(snapshot["restored"], source_registry_present=False)
    _assert_snapshot_and_external_original_unchanged(snapshot)
