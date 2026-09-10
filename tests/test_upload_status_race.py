"""Generated HTTP interleavings for full upload-status reconciliation."""
import pytest
from fastapi.testclient import TestClient

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.managed_storage import StoragePolicy
from case_intelligence.workbench import create_workbench_app

from case_intelligence.intake_receipts import IntakeReceipts
from case_intelligence.workspace_store import WorkspaceProblem
from tests.test_intake_receipt_http import ACTOR, descriptor, selection, upload, put


@pytest.fixture
def workspace(tmp_path):
    with TestClient(create_workbench_app(
        tmp_path / 'runtime', generator=UnavailableGenerator(), auth_mode='test',
        background_ingestion=True, ingestion_workers=1,
        storage_policy=StoragePolicy(reserve_bytes=0),
    )) as client:
        response = client.post('/matters', data={
            'name': 'Synthetic concurrent intake', 'descriptor': 'Generated status race',
        }, follow_redirects=False)
        assert response.status_code == 303
        bench = client.app.state.workbench
        yield client, bench, bench.matter(response.headers['location'].split('/')[2], ACTOR)


def prepared(workspace):
    client, bench, matter = workspace
    body = b'Synthetic concurrent upload status passage.\n'
    files = [descriptor('Generated/report.txt', len(body))]
    receipt = selection(client, matter.slug, files, [0])
    session = upload(client, matter.slug, receipt, files, [0])
    return client, bench, matter, body, receipt, session, session['items'][0]


@pytest.mark.parametrize('advance', ['chunk', 'finalize', 'cancel'])
def test_status_refreshes_after_concurrent_http_transition(workspace, monkeypatch, advance):
    client, bench, matter, body, receipt, session, item = prepared(workspace)
    put(client, item, body[:7])
    original = bench.workspace.upload_session
    armed = True

    def snapshot_then_advance(*args, **kwargs):
        nonlocal armed
        snapshot = original(*args, **kwargs)
        if armed:
            armed = False
            if advance == 'cancel':
                response = client.post(session['status_url'] + '/cancel')
                assert response.status_code == 200, response.text
            else:
                put(client, item, body[7:], 7)
                if advance == 'finalize':
                    response = client.post(item['finalize_url'])
                    assert response.status_code == 200, response.text
        return snapshot

    monkeypatch.setattr(bench.workspace, 'upload_session', snapshot_then_advance)
    response = client.get(session['status_url'])
    assert response.status_code == 200, response.text
    current = response.json()
    assert not armed
    expected_state = {'chunk': 'uploaded', 'finalize': 'queued', 'cancel': 'cancelled'}[advance]
    assert current['state'] == {'chunk': 'open', 'finalize': 'complete', 'cancel': 'cancelled'}[advance]
    assert current['items'][0]['state'] == expected_state
    assert current['items'][0]['received_size'] == (7 if advance == 'cancel' else len(body))
    assert current['upload_session_id'] == session['upload_session_id']
    assert current['collection_id'] == session['collection_id']
    if advance == 'cancel':
        assert current['state'] == 'cancelled'
        assert not bench.source_store(matter).documents
        return
    assert client.post(item['finalize_url']).status_code == 200
    assert client.post(item['finalize_url']).status_code == 200
    store = bench.source_store(matter)
    assert len(store.documents) == 1
    document = next(iter(store.documents.values()))
    assert store.source_path(document.document_id).read_bytes() == body
    row = IntakeReceipts(bench.workspace).snapshot(matter.matter_id, ACTOR, receipt['receipt_id'])['items'][0]
    assert (row['catalog_document_id'], row['version_id']) == (document.document_id, document.version_id)


@pytest.mark.parametrize('competing', [True, False])
def test_status_cas_conflict_only_recovers_changed_ledger(workspace, monkeypatch, competing):
    client, bench, matter, body, receipt, session, item = prepared(workspace)
    record = bench.workspace.upload_session(matter.matter_id, ACTOR, session['upload_session_id'])[1][0]
    # Simulate bytes persisted before an interrupted ledger commit.
    bench.source_store(matter).append_resumable_chunk(record.upload_item_id,
        expected_size=len(body), offset=0, chunk=body[:7])
    original = bench.workspace.set_upload_item_offset

    def competing_commit(*args, **kwargs):
        if competing:
            original(*args, **kwargs)
            return original(*args, **kwargs)  # Real stale-offset rejection.
        raise WorkspaceProblem('Synthetic unrelated ledger failure')

    monkeypatch.setattr(bench.workspace, 'set_upload_item_offset', competing_commit)
    if not competing:
        with pytest.raises(WorkspaceProblem, match='unrelated ledger failure'):
            client.get(session['status_url'])
        return
    response = client.get(session['status_url'])
    assert response.status_code == 200, response.text
    assert response.json()['items'][0]['received_size'] == 7
    assert response.json()['items'][0]['state'] == 'uploading'
    with pytest.raises(WorkspaceProblem, match='offset changed'):
        original(matter.matter_id, ACTOR, session['upload_session_id'], record.upload_item_id, 0, 7)


@pytest.mark.parametrize('damage', ['missing', 'oversized', 'uncommitted'])
def test_status_keeps_byte_recovery_distinct_from_concurrency(workspace, damage):
    client, bench, matter, body, receipt, session, item = prepared(workspace)
    put(client, item, body[:7])
    store = bench.source_store(matter)
    record = bench.workspace.upload_session(matter.matter_id, ACTOR, session['upload_session_id'])[1][0]
    path = store.incoming / store._resumable_name(record.upload_item_id)
    if damage == 'missing':
        path.unlink()
    elif damage == 'oversized':
        path.write_bytes(body + b'generated excess')
    else:
        store.append_resumable_chunk(record.upload_item_id, expected_size=len(body), offset=7, chunk=body[7:])
    response = client.get(session['status_url'])
    assert response.status_code == 200, response.text
    current = response.json()['items'][0]
    assert current['state'] == ('uploaded' if damage == 'uncommitted' else 'failed')
    assert current['received_size'] == (len(body) if damage == 'uncommitted' else 7)
    if damage != 'uncommitted':
        assert 'incomplete' in current['message'] if damage == 'missing' else 'safely' in current['message']


def test_foreign_status_cannot_reconcile_another_matter(workspace, monkeypatch):
    client, bench, matter, body, receipt, session, item = prepared(workspace)
    foreign = bench.create_matter('Synthetic foreign status', '', 'development-jordan-lee')

    def forbidden(*args, **kwargs):
        pytest.fail('Unauthorized status reached staged bytes')

    monkeypatch.setattr(bench.source_store(matter), 'resumable_size', forbidden)
    own_other = bench.create_matter('Synthetic other status', '', ACTOR)
    for slug in (own_other.slug, foreign.slug):
        response = client.get(session['status_url'].replace(matter.slug, slug))
        assert response.status_code == 404


@pytest.mark.parametrize('transition', ['none', 'cancelled', 'queued'])
@pytest.mark.parametrize('inspection', ['valid', 'missing', 'unsafe'])
def test_slow_inspection_allows_unrelated_work_and_preserves_terminal_commits(
    workspace, monkeypatch, transition, inspection,
):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from case_intelligence.pilot_uploads import UploadProblem

    client, bench, matter, body, receipt, session, item = prepared(workspace)
    put(client, item, body)
    store = bench.source_store(matter)
    record = bench.workspace.upload_session(matter.matter_id, ACTOR, session['upload_session_id'])[1][0]
    # Finalization persists the source before committing its ledger transition.
    document = store.finalize_resumable_upload(record.upload_item_id,
        display_name=record.display_name, relative_path=record.relative_path,
        content_type=record.media_type, expected_size=record.expected_size)
    entered = threading.Event()
    release = threading.Event()
    original = store.resumable_size

    def slow_inspection(*args, **kwargs):
        entered.set()
        assert release.wait(5), 'Synthetic filesystem inspection was not released'
        if inspection == 'unsafe':
            raise UploadProblem('Synthetic unsafe staging file', 409)
        return 0 if inspection == 'missing' else original(*args, **kwargs)

    def unrelated_work_and_transition():
        other = bench.create_matter('Synthetic unrelated concurrent matter', '', ACTOR)
        assert bench.workspace.membership(other.matter_id, ACTOR)
        if transition == 'cancelled':
            bench.workspace.cancel_upload_session(matter.matter_id, ACTOR, session['upload_session_id'])
        elif transition == 'queued':
            bench.workspace.finish_upload_item(matter.matter_id, ACTOR,
                session['upload_session_id'], record.upload_item_id, document.document_id,
                queue_ingestion=False, source_version_id=document.version_id)

    monkeypatch.setattr(store, 'resumable_size', slow_inspection)
    with ThreadPoolExecutor(max_workers=2) as pool:
        status = pool.submit(client.get, session['status_url'])
        try:
            assert entered.wait(5), 'Status did not reach generated staging inspection'
            # This must finish while the filesystem remains blocked.
            pool.submit(unrelated_work_and_transition).result(timeout=2)
        finally:
            release.set()
        response = status.result(timeout=5)
    assert response.status_code == 200, response.text
    result = response.json()
    expected = transition if transition != 'none' else ('uploaded' if inspection == 'valid' else 'failed')
    assert result['items'][0]['state'] == expected
    if transition != 'none':
        assert result['state'] == ('cancelled' if transition == 'cancelled' else 'complete')
    assert result['items'][0]['received_size'] == len(body)
