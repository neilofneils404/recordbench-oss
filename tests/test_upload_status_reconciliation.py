"""Status polling must not regress an upload that progressed concurrently."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from fastapi.testclient import TestClient
import pytest

from case_intelligence.intake_receipts import IntakeReceipts
from tests.test_intake_receipt_http import ACTOR, descriptor, selection, upload, put, workspace  # noqa: F401

BODY = b"Generated exact concurrent upload support.\n"


def selected(workspace):
    client, bench, matter = workspace
    files = [descriptor("Generated/record.txt", len(BODY))]
    receipt = selection(client, matter.slug, files, [0])
    session = upload(client, matter.slug, receipt, files, [0])
    return receipt, session, session["items"][0]


@pytest.mark.parametrize("progress", ["chunk", "finalize", "cancel"])
def test_stale_status_snapshot_preserves_concurrent_progress(workspace, monkeypatch, progress):
    client, bench, matter = workspace
    receipt, session, item = selected(workspace)
    if progress == "finalize":
        put(client, item, BODY)
    elif progress == "cancel":
        put(client, item, BODY[:7])
    waiting = threading.Event()
    release = threading.Event()
    source_store = bench.source_store
    store = source_store(matter)

    def paused_store(*args, **kwargs):
        if not waiting.is_set():
            waiting.set()
            assert release.wait(8)
        return source_store(*args, **kwargs)

    monkeypatch.setattr(bench, "source_store", paused_store)
    reader = TestClient(client.app, raise_server_exceptions=False)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            status = pool.submit(reader.get, session["status_url"])
            try:
                assert waiting.wait(5)
                if progress == "chunk":
                    put(client, item, BODY[:7])
                elif progress == "finalize":
                    assert client.post(item["finalize_url"]).status_code == 200
                else:
                    assert client.post(session["cancel_url"]).status_code == 200
            finally:
                release.set()
            response = status.result(timeout=5)
        assert response.status_code == 200, response.text
        projection = response.json()
        if progress == "cancel":
            assert projection["state"] == "cancelled"
            assert projection["items"][0]["state"] == "cancelled"
            assert store.resumable_size(item["upload_item_id"], expected_size=len(BODY)) == 0
            assert not store.documents
        else:
            if progress == "chunk":
                assert projection["items"][0]["received_size"] == 7
                assert projection["items"][0]["state"] == "uploading"
                put(client, item, BODY[7:], offset=7)
                assert client.post(item["finalize_url"]).status_code == 200
            else:
                assert projection["state"] == "complete"
                assert projection["items"][0]["state"] == "queued"
            deadline = time.monotonic() + 8
            while any(bench.workspace.active_matter_work_counts(matter.matter_id).values()):
                assert time.monotonic() < deadline
                time.sleep(.02)
            document = next(iter(store.documents.values()))
            assert len(store.documents) == 1 and store.source_path(document.document_id).read_bytes() == BODY
            row = IntakeReceipts(bench.workspace).snapshot(matter.matter_id, ACTOR, receipt["receipt_id"])["items"][0]
            assert (row["catalog_document_id"], row["version_id"]) == (document.document_id, document.version_id)
            assert client.get(f"/matters/{matter.slug}/sources/{store.action_token(document)}").status_code == 200
            assert client.get(receipt["receipt_url"] + "/export?format=json").json()["counts"]["received"] == 1
    finally:
        release.set()
        reader.close()


@pytest.mark.parametrize("saved_state", ["ahead", "missing"])
def test_cancellation_during_offset_recovery_returns_current_terminal_state(workspace, monkeypatch, saved_state):
    client, bench, matter = workspace
    _, session, item = selected(workspace)
    store = bench.source_store(matter)
    # A stopped transfer can leave saved bytes ahead of its control checkpoint.
    if saved_state == "ahead":
        store.append_resumable_chunk(item["upload_item_id"], offset=0, expected_size=len(BODY), chunk=BODY[:7])
    else:
        put(client, item, BODY[:7])
        store.discard_resumable_upload(item["upload_item_id"])
    inspected = threading.Event()
    cancellation_recorded = threading.Event()
    original_size = store.resumable_size
    original_cancel = bench.workspace.cancel_upload_session

    def paused_size(*args, **kwargs):
        actual = original_size(*args, **kwargs)
        inspected.set()
        assert cancellation_recorded.wait(8)
        return actual

    def cancel(*args, **kwargs):
        result = original_cancel(*args, **kwargs)
        cancellation_recorded.set()
        return result

    monkeypatch.setattr(store, "resumable_size", paused_size)
    monkeypatch.setattr(bench.workspace, "cancel_upload_session", cancel)
    reader = TestClient(client.app, raise_server_exceptions=False)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            status = pool.submit(reader.get, session["status_url"])
            assert inspected.wait(5)
            cancelled = pool.submit(client.post, session["cancel_url"])
            response = status.result(timeout=5)
            assert cancelled.result(timeout=5).status_code == 200
        assert response.status_code == 200
        assert response.json()["state"] == "cancelled"
        assert response.json()["items"][0]["state"] == "cancelled"
        assert original_size(item["upload_item_id"], expected_size=len(BODY)) == 0
    finally:
        cancellation_recorded.set()
        reader.close()


def test_actual_missing_bytes_still_require_recovery(workspace):
    client, bench, matter = workspace
    receipt, session, item = selected(workspace)
    put(client, item, BODY[:7])
    bench.source_store(matter).discard_resumable_upload(item["upload_item_id"])
    result = client.get(session["status_url"])
    assert result.status_code == 200
    assert result.json()["items"][0]["state"] == "failed"
    assert "saved upload is incomplete" in result.json()["items"][0]["message"]
    assert client.get(receipt["receipt_url"]).status_code == 200


def test_foreign_status_cannot_reconcile_another_matters_bytes(workspace):
    client, bench, matter = workspace
    _, session, item = selected(workspace)
    other = bench.create_matter("Generated status boundary", "", ACTOR)
    put(client, item, BODY[:7])
    assert client.get(session["status_url"].replace(matter.slug, other.slug)).status_code == 404
    assert bench.workspace.upload_item(matter.matter_id, ACTOR, session["upload_session_id"], item["upload_item_id"]).received_size == 7


def test_unresolved_checkpoint_error_remains_a_recoverable_failure(workspace, monkeypatch):
    from case_intelligence.workspace_store import WorkspaceProblem
    client, bench, matter = workspace
    _, session, item = selected(workspace)
    store = bench.source_store(matter)
    store.append_resumable_chunk(item["upload_item_id"], offset=0, expected_size=len(BODY), chunk=BODY[:7])
    def blocked(*_args, **_kwargs):
        raise WorkspaceProblem("Refresh the saved upload status and try again.")
    monkeypatch.setattr(bench.workspace, "set_upload_item_offset", blocked)
    response = client.get(session["status_url"])
    assert response.status_code == 409
    assert response.json()["message"] == "Refresh the saved upload status and try again."
    assert store.resumable_size(item["upload_item_id"], expected_size=len(BODY)) == 7
    assert bench.workspace.upload_item(matter.matter_id, ACTOR, session["upload_session_id"], item["upload_item_id"]).received_size == 0
