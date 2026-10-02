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
    current = dict(document_id=document.document_id, source_version_id="synthetic-newer-version",
                   content_basis_digest="")
    with repo.transaction(matter.matter_id, AUTOMATIC_DISCOVERY_PRINCIPAL):
        repo.connection.execute(
            "INSERT INTO workbench_entity_auto_discovery_unit (matter_id,document_id,source_version_id,"
            "content_basis_digest,unit_ordinal,unit_digest,extractor_version,state) VALUES (?,?,?,?,?,?,?,?)",
            (matter.matter_id, document.document_id, old_version, "", 9, "0" * 64, "synthetic-older", "pending"))
        assert repo.seal_auto_discovery(matter.matter_id, current, "synthetic-older", [(1, "1" * 64)])
        assert not repo.seal_auto_discovery(matter.matter_id, current, "synthetic-older", [(1, "1" * 64)])
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


def long_text(units, marker):
    # Text sources split into 20-line units; one synthetic name per unit.
    return "\n".join(f"{marker} Example{index // 20} called on line {index}." for index in range(units * 20)).encode()


def test_sealed_sources_load_only_pending_units(workbench, monkeypatch):
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic long log.txt", long_text(30, "Alex"))
    calls = []
    original = bench.automatic_entity_discovery
    def counting(target):
        discovery = original(target)
        loader = discovery.load_document
        def load_document(document_id, source_version_id, ordinals=None):
            calls.append(None if ordinals is None else len(ordinals))
            return loader(document_id, source_version_id, ordinals)
        discovery.load_document = load_document
        return discovery
    monkeypatch.setattr(bench, "automatic_entity_discovery", counting)
    assert bench.run_automatic_discovery_once(unit_limit=25) == 25
    assert bench.run_automatic_discovery_once() == 5
    # One full inventory pass, then only the pending ordinals.
    assert calls == [None, 25, 5]
    assert bench.run_automatic_discovery_once() == 0 and calls == [None, 25, 5]


def test_inventory_respects_the_byte_budget_before_writing(workbench, monkeypatch):
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic long log.txt", long_text(30, "Alex"))
    original = bench.automatic_entity_discovery
    used = bench.workspace.entity_repository().discovery_storage_bytes
    def tight(target):
        discovery = original(target)
        with bench.workspace._lock:
            discovery.byte_limit = max(4096, used(target.matter_id) + 4096 + 1000)
        return discovery
    monkeypatch.setattr(bench, "automatic_entity_discovery", tight)
    assert bench.run_automatic_discovery_once() == 0
    rows = bench.workspace.connection.execute(
        "SELECT unit_ordinal,state,note FROM workbench_entity_auto_discovery_unit WHERE matter_id=?",
        (matter.matter_id,)).fetchall()
    assert [(row[0], row[1]) for row in rows] == [(0, "failed")]
    assert "byte budget" in rows[0][2]
    assert used(matter.matter_id) <= tight(matter).byte_limit


def test_unavailable_sources_do_not_stall_a_run(workbench, monkeypatch):
    client, bench, matter, _runtime = workbench
    for index in range(7):
        upload(client, matter.slug, f"Synthetic memo {index}.txt", f"Riley Placeholder{index} arrived.".encode())
    documents = sorted(bench.source_store(matter).documents)
    readable = documents[-1]
    original = bench.automatic_entity_discovery
    def mostly_unavailable(target):
        discovery = original(target)
        loader = discovery.load_document
        def load_document(document_id, source_version_id, ordinals=None):
            if document_id != readable:
                raise KeyError(document_id)
            return loader(document_id, source_version_id, ordinals)
        discovery.load_document = load_document
        return discovery
    monkeypatch.setattr(bench, "automatic_entity_discovery", mostly_unavailable)
    # Six unavailable sources seal as failed first; the run continues to the seventh.
    assert bench.run_automatic_discovery_once() == 1
    progress = bench.automatic_entity_discovery(matter).automatic_progress(matter.matter_id)
    assert progress["unsealed_sources"] == 0 and progress["processed"] == 1


def test_changed_extracted_text_is_rediscovered(workbench):
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    assert bench.run_automatic_discovery_once() == 1
    document = next(iter(bench.source_store(matter).documents.values()))
    # Same source version, new extracted basis (for example an OCR retry).
    with bench.workspace._lock, bench.workspace.connection:
        bench.workspace.connection.execute(
            "UPDATE workbench_source_catalog SET content_basis_digest=? WHERE matter_id=? AND document_id=?",
            ("9" * 64, matter.matter_id, document.document_id))
    discovery = bench.automatic_entity_discovery(matter)
    assert discovery.automatic_progress(matter.matter_id)["unsealed_sources"] == 1
    assert bench.run_automatic_discovery_once() == 1
    seals = bench.workspace.connection.execute(
        "SELECT content_basis_digest FROM workbench_entity_auto_discovery_unit WHERE matter_id=? "
        "AND unit_ordinal=0 ORDER BY content_basis_digest", (matter.matter_id,)).fetchall()
    assert len(seals) == 2 and "9" * 64 in {row[0] for row in seals}
    # The same passages are not suggested twice.
    assert len(names(bench, matter)) == 4


def test_every_automatic_unit_is_audited(workbench):
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    upload(client, matter.slug, "Synthetic second memo.txt", SECOND)
    assert bench.run_automatic_discovery_once() == 2
    events = [event for event in bench.workspace.audit_events(matter.matter_id)
              if event.action == "entity.discovery_unit"]
    assert len(events) == 2
    assert {event.actor_principal_id for event in events} == {AUTOMATIC_DISCOVERY_PRINCIPAL}
    assert {event.outcome for event in events} == {"success"}
    assert {event.object_type for event in events} == {"source"}


def test_a_failing_audit_rolls_back_its_unit(workbench, monkeypatch):
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    original = bench.workspace._append_audit_event_locked
    def refuse(**_values):
        raise RuntimeError("synthetic audit outage")
    monkeypatch.setattr(bench.workspace, "_append_audit_event_locked", refuse)
    result = bench.automatic_discovery_pass()
    assert result.units == 0 and result.failed_matters == (matter.matter_id,)
    # Nothing from the unit committed without its audit record.
    assert names(bench, matter) == []
    states = {row[0] for row in bench.workspace.connection.execute(
        "SELECT state FROM workbench_entity_auto_discovery_unit WHERE matter_id=? AND unit_ordinal>0",
        (matter.matter_id,))}
    assert states == {"pending"}
    monkeypatch.setattr(bench.workspace, "_append_audit_event_locked", original)
    assert bench.run_automatic_discovery_once() == 1
    assert len(names(bench, matter)) == 4
    assert len([event for event in bench.workspace.audit_events(matter.matter_id)
                if event.action == "entity.discovery_unit"]) == 1


def test_one_failing_matter_does_not_stop_the_others(workbench, monkeypatch):
    client, bench, matter, _runtime = workbench
    other = bench.matter(_create_matter(client, "Synthetic second matter"), WEB_ACTOR)
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    upload(client, other.slug, "Synthetic memo.txt", SECOND)
    original = bench.automatic_entity_discovery
    def broken_first(target):
        if target.matter_id == min(matter.matter_id, other.matter_id):
            raise RuntimeError("synthetic unreadable source registry")
        return original(target)
    monkeypatch.setattr(bench, "automatic_entity_discovery", broken_first)
    result = bench.automatic_discovery_pass()
    assert result.failed_matters == (min(matter.matter_id, other.matter_id),)
    assert result.units == 1


def test_sealing_is_reported_as_progress_when_the_step_cap_is_reached(workbench, monkeypatch):
    import case_intelligence.workbench as workbench_module
    client, bench, matter, _runtime = workbench
    for index in range(7):
        upload(client, matter.slug, f"Synthetic memo {index}.txt", f"Riley Placeholder{index} arrived.".encode())
    original = bench.automatic_entity_discovery
    def unavailable(target):
        discovery = original(target)
        def load_document(document_id, source_version_id, ordinals=None):
            raise KeyError(document_id)
        discovery.load_document = load_document
        return discovery
    monkeypatch.setattr(bench, "automatic_entity_discovery", unavailable)
    monkeypatch.setattr(workbench_module, "MAX_AUTOMATIC_DISCOVERY_STEPS", 1)
    result = bench.automatic_discovery_pass()
    # One capped step sealed five sources: no units, but real progress to continue from.
    assert result.units == 0 and result.progress == 5 and not result.failed_matters
    assert bench.automatic_discovery_pass().progress == 2
    assert bench.automatic_discovery_pass().progress == 0
