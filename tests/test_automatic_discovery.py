"""Synthetic regression: suggestions appear after processing, without a model or a person."""
from __future__ import annotations

import shutil
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from case_intelligence.workbench import AutomaticDiscoveryCoordinator, create_workbench_app
from case_intelligence.workspace_store import AUTOMATIC_DISCOVERY_PRINCIPAL, WorkspaceStore
from tests.test_matter_notebook import WEB_ACTOR, _create_matter

FIRST = b"Alex Example met Jordan Sample. Amber Cooperative opened on 03/04/2026."
SECOND = b"Alex Example met Riley Placeholder. ID: ZX-204."


def upload(client, slug, name, content):
    response = client.post(f"/matters/{slug}/uploads", files=[("files", (name, content, "text/plain"))])
    assert response.status_code in (200, 303), response.text


@pytest.fixture
def workbench(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE_INTELLIGENCE_STORAGE_RESERVE_GIB", "0")
    monkeypatch.delenv("CASE_INTELLIGENCE_AUTOMATIC_DISCOVERY", raising=False)
    runtime = tmp_path / "runtime"
    with TestClient(create_workbench_app(runtime, auth_mode="test")) as client:
        slug = _create_matter(client)
        bench = client.app.state.workbench
        yield client, bench, bench.matter(slug, WEB_ACTOR), runtime


def names(bench, matter):
    service = bench.entity_service(matter)
    rows, _total = service.list(matter.matter_id, WEB_ACTOR)
    return sorted((row["display_name"], row["status"]) for row in rows)


def test_processing_yields_suggestions_without_a_model_or_a_review_run(workbench):
    client, bench, matter, _runtime = workbench
    assert bench.automatic_discovery is None  # Off unless the deployment enables it.
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    assert bench.run_automatic_discovery_once() == 1
    assert names(bench, matter) == [
        ("03/04/2026", "suggested"), ("Alex Example", "suggested"),
        ("Amber Cooperative", "suggested"), ("Jordan Sample", "suggested")]
    # Nothing is reprocessed on the next pass.
    assert bench.run_automatic_discovery_once() == 0
    assert bench.workspace.connection.execute(
        "SELECT COUNT(*) FROM workbench_review_run WHERE matter_id=?", (matter.matter_id,)).fetchone()[0] == 0
    progress = bench.automatic_entity_discovery(matter).automatic_progress(matter.matter_id)
    assert progress == dict(pending=0, processed=1, failed=0, unsealed_sources=0,
                            sources_complete=1, sources_ready=1, suggested=4)
    # Suggestions are attributed to the inactive system principal.
    creators = {row[0] for row in bench.workspace.connection.execute(
        "SELECT created_by FROM workbench_entity WHERE matter_id=?", (matter.matter_id,))}
    assert creators == {AUTOMATIC_DISCOVERY_PRINCIPAL}
    page = client.get(f"/matters/{matter.slug}/entities")
    assert page.status_code == 200 and "Jordan Sample" in page.text


def test_new_version_supersedes_without_touching_human_decisions(workbench):
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    bench.run_automatic_discovery_once()
    service = bench.entity_service(matter)
    rows, _ = service.list(matter.matter_id, WEB_ACTOR)
    jordan = next(row for row in rows if row["display_name"] == "Jordan Sample")
    service.update(matter.matter_id, WEB_ACTOR, jordan["entity_id"], expected_revision=jordan["revision"],
                   display_name="Jordan Sample (reviewed)", status="confirmed")
    store = bench.source_store(matter)
    document = next(iter(store.documents.values()))
    old_version = document.version_id
    # A second source is discovered; the reviewed identity is untouched.
    upload(client, matter.slug, "Synthetic second memo.txt", SECOND)
    assert bench.run_automatic_discovery_once() == 1
    rows, _ = service.list(matter.matter_id, WEB_ACTOR)
    assert ("Jordan Sample (reviewed)", "confirmed") in {(row["display_name"], row["status"]) for row in rows}
    assert "Riley Placeholder" in {row["display_name"] for row in rows}
    # A newer version of a source seals afresh and stops unfinished older work.
    repo = bench.workspace.entity_repository(automatic=True)
    with repo.transaction(matter.matter_id, AUTOMATIC_DISCOVERY_PRINCIPAL):
        repo.connection.execute(
            "INSERT INTO workbench_entity_auto_discovery_unit VALUES (?,?,?,?,?,?,?,?)",
            (matter.matter_id, document.document_id, old_version, 9, "0" * 64, "synthetic-older", "pending", ""))
        assert repo.seal_auto_discovery(matter.matter_id, document.document_id, "synthetic-newer-version",
                                        "synthetic-older", [(1, "1" * 64)])
        assert not repo.seal_auto_discovery(matter.matter_id, document.document_id, "synthetic-newer-version",
                                            "synthetic-older", [(1, "1" * 64)])
        state = repo.connection.execute(
            "SELECT state FROM workbench_entity_auto_discovery_unit WHERE matter_id=? AND source_version_id=? "
            "AND unit_ordinal=9", (matter.matter_id, old_version)).fetchone()[0]
    assert state == "invalidated"
    assert ("Jordan Sample (reviewed)", "confirmed") in names(bench, matter)


def test_only_the_system_principal_on_an_active_matter_is_authorized(workbench):
    _client, bench, matter, _runtime = workbench
    repo = bench.workspace.entity_repository(automatic=True)
    with pytest.raises(KeyError):
        with repo.transaction(matter.matter_id, WEB_ACTOR):
            pass
    with pytest.raises(KeyError):
        with repo.transaction("ci-matter-" + "0" * 32, AUTOMATIC_DISCOVERY_PRINCIPAL):
            pass
    # The system principal cannot use the ordinary membership path.
    with pytest.raises(KeyError):
        with bench.workspace.entity_repository().transaction(matter.matter_id, AUTOMATIC_DISCOVERY_PRINCIPAL):
            pass
    lookup = "SELECT active FROM workbench_principal WHERE principal_id=?"
    # Refused attempts create nothing; the principal appears on first real use.
    assert bench.workspace.connection.execute(lookup, (AUTOMATIC_DISCOVERY_PRINCIPAL,)).fetchone() is None
    with repo.transaction(matter.matter_id, AUTOMATIC_DISCOVERY_PRINCIPAL):
        pass
    assert bench.workspace.connection.execute(lookup, (AUTOMATIC_DISCOVERY_PRINCIPAL,)).fetchone()[0] == 0
    assert AUTOMATIC_DISCOVERY_PRINCIPAL not in {
        principal.principal_id for principal in bench.workspace.active_principals()}


def test_a_fresh_store_still_starts_without_principals(tmp_path):
    store = WorkspaceStore(tmp_path / "workbench.sqlite")
    try:
        assert store.connection.execute("SELECT COUNT(*) FROM workbench_principal").fetchone()[0] == 0
    finally:
        store.close()


def test_coordinator_runs_after_a_source_becomes_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE_INTELLIGENCE_STORAGE_RESERVE_GIB", "0")
    monkeypatch.setenv("CASE_INTELLIGENCE_AUTOMATIC_DISCOVERY", "1")
    with TestClient(create_workbench_app(tmp_path / "runtime", auth_mode="test")) as client:
        bench = client.app.state.workbench
        assert isinstance(bench.automatic_discovery, AutomaticDiscoveryCoordinator)
        slug = _create_matter(client)
        matter = bench.matter(slug, WEB_ACTOR)
        upload(client, slug, "Synthetic memo.txt", FIRST)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and len(names(bench, matter)) < 4:
            time.sleep(0.05)
        assert ("Jordan Sample", "suggested") in names(bench, matter)
        assert bench.automatic_discovery.status() == {"enabled": True, "last_error": ""}


def test_restore_export_purge_and_idempotent_migration(workbench, tmp_path):
    client, bench, matter, runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    bench.run_automatic_discovery_once()
    expected = bench.workspace.entity_repository().discovery_export(matter.matter_id)
    assert [row["unit_ordinal"] for row in expected["automatic_coverage"]] == [0, 1]
    assert expected["occurrence_tombstones"]
    before = names(bench, matter)
    client.__exit__(None, None, None)
    restored = tmp_path / "restored"
    shutil.copytree(runtime, restored)
    with TestClient(create_workbench_app(restored, auth_mode="test")) as again:
        bench = again.app.state.workbench
        matter = bench.matter(matter.slug, WEB_ACTOR)
        assert bench.workspace.entity_repository().discovery_export(matter.matter_id) == expected
        assert names(bench, matter) == before
        # Already discovered; a restored node does not duplicate suggestions.
        assert bench.run_automatic_discovery_once() == 0
        _, lifecycle = bench.workspace.begin_matter_purge(matter.slug, WEB_ACTOR, matter.display_name, source_count=1)
        bench.workspace.complete_matter_purge(matter.matter_id, lifecycle.purge_id)
        count = bench.workspace.connection.execute(
            "SELECT COUNT(*) FROM workbench_entity_auto_discovery_unit WHERE matter_id=?",
            (matter.matter_id,)).fetchone()[0]
        assert count == 0
    # Re-running every migration on the restored store changes nothing.
    database = restored / "workbench.sqlite"
    before_schema = sqlite3.connect(database).execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    WorkspaceStore(database).connection.close()
    after_schema = sqlite3.connect(database).execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    assert before_schema == after_schema


def test_home_readiness_reports_discovery_and_links_to_suggestions(workbench, monkeypatch):
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    status = client.get(f"/matters/{matter.slug}/processing-status").json()
    assert status["discovery"] == {"label": "", "href": "", "working": False}  # Disabled deployment.
    class Enabled:
        def close(self):
            pass
    monkeypatch.setattr(bench, "automatic_discovery", Enabled())
    status = client.get(f"/matters/{matter.slug}/processing-status").json()
    assert status["discovery"]["label"] == "Finding people and dates · 0 of 1 sources"
    assert status["discovery"]["working"] is True
    bench.run_automatic_discovery_once()
    status = client.get(f"/matters/{matter.slug}/processing-status").json()
    assert status["discovery"] == {
        "label": "4 suggested people, things and dates to review",
        "href": f"/matters/{matter.slug}/entities", "working": False}
    home = client.get(f"/matters/{matter.slug}/home").text
    assert f'data-readiness-discovery href="/matters/{matter.slug}/entities">4 suggested' in home


def test_system_provider_is_reserved_for_internal_principals(workbench):
    from case_intelligence.workspace_store import WorkspaceProblem
    _client, bench, matter, _runtime = workbench
    repo = bench.workspace.entity_repository(automatic=True)
    with repo.transaction(matter.matter_id, AUTOMATIC_DISCOVERY_PRINCIPAL):
        pass
    with pytest.raises(WorkspaceProblem):
        bench.workspace.upsert_principal("system", "automatic-discovery", "Impostor", "impostor")
    row = bench.workspace.connection.execute(
        "SELECT display_name, active FROM workbench_principal WHERE principal_id=?",
        (AUTOMATIC_DISCOVERY_PRINCIPAL,)).fetchone()
    assert tuple(row) == ("Automatic discovery", 0)
