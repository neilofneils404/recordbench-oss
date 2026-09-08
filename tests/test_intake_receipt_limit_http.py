"""Receipt admission, final export and owner cleanup through normal HTTP routes."""
import pytest

from tests.test_intake_receipt_http import ACTOR, workspace  # noqa: F401
from tests.test_intake_receipt_limits import limits


def test_full_matter_retains_export_and_owner_can_discard_unfinished_selection(workspace, monkeypatch):
    client, bench, matter = workspace
    limits(monkeypatch, 'matter', (2, 3, 1024 * 1024))
    root = f'/matters/{matter.slug}/intake-receipts'

    def create(key, count):
        return client.post(root, json={'selection_key': key * 32, 'selection_fingerprint': 'f' * 64,
            'selected_count': count, 'eligible_indexes': [], 'collection_name': 'Generated unfinished selection'})

    first = create('1', 1).json()
    assert create('2', 2).status_code == 201
    blocked = create('3', 1)
    assert blocked.status_code == 409 and 'matter owner' in blocked.json()['message']
    assert client.get(f'/matters/{matter.slug}/export').status_code == 200
    page = client.get(first['receipt_url'])
    assert 'Discard receipt' in page.text
    discarded = client.post(first['receipt_url'] + '/discard', data={})
    assert discarded.status_code == 200 and 'Confirm that you want to discard' in discarded.text
    assert client.get(first['receipt_url']).status_code == 200
    discarded = client.post(first['receipt_url'] + '/discard', data={'confirm': 'yes'})
    assert discarded.status_code == 200 and 'Receipt discarded.' in discarded.text
    assert client.get(first['receipt_url']).status_code == 404
    assert create('3', 1).status_code == 201
    assert client.get(f'/matters/{matter.slug}/export').status_code == 200


def test_foreign_matter_receipt_cleanup_is_inaccessible(workspace):
    client, bench, matter = workspace
    from case_intelligence.intake_receipts import IntakeReceipts
    other = 'generated-receipt-owner'
    bench.workspace.upsert_principal('test', other, 'Generated receipt owner', other, preferred_principal_id=other)
    foreign = bench.create_matter('Generated foreign receipt matter', '', other)
    receipt = IntakeReceipts(bench.workspace).create(foreign.matter_id, other,
        selection_key='c' * 32, selection_fingerprint='d' * 64, selected_count=1,
        eligible_indexes=[], collection_name='Generated foreign receipt canary')
    path = f"/matters/{foreign.slug}/intake/{receipt['receipt_id']}"
    assert client.get(path).status_code == 404
    assert client.post(path + '/discard', data={'confirm': 'yes'}).status_code == 404
    assert IntakeReceipts(bench.workspace).get(foreign.matter_id, other, receipt['receipt_id'])['state'] == 'recording'


@pytest.mark.parametrize('bound', [False, True])
def test_owner_recovers_capacity_after_member_selection_and_revocation(workspace, monkeypatch, bound):
    from case_intelligence.intake_receipts import IntakeReceipts
    from tests.test_intake_receipt_http import descriptor, selection
    client, bench, matter = workspace
    member = 'generated-selection-member'
    bench.workspace.upsert_principal('test', member, 'Generated member', member, preferred_principal_id=member)
    bench.workspace.add_member(matter.matter_id, member, ACTOR)
    receipts = IntakeReceipts(bench.workspace)
    limits(monkeypatch, 'matter', (1, 3, 1024 * 1024))
    receipt = receipts.create(matter.matter_id, member, selection_key='c' * 32,
        selection_fingerprint='d' * 64, selected_count=1, eligible_indexes=[0] if bound else [], collection_name='Generated selection')
    receipts.append(matter.matter_id, member, receipt['receipt_id'], start=0,
        files=[descriptor('Generated/record.txt' if bound else 'Generated/opaque.bin', 48)],
        reviewed_states=['valid' if bound else 'unsupported'],
        document_limit=1024, media_limit=2048, malware_scan_mode='off', scanner_ready=True)
    receipts.seal(matter.matter_id, member, receipt['receipt_id'])
    if bound:
        session, _ = bench.create_upload_session(matter, member, 'Generated selection',
            [{'display_name': 'record.txt', 'relative_path': 'Generated/record.txt', 'media_type': 'text/plain', 'expected_size': 48}],
            intake_receipt_id=receipt['receipt_id'], intake_ordinals=[0])
    bench.workspace.revoke_member(matter.matter_id, member, ACTOR)
    url = f"/matters/{matter.slug}/intake/{receipt['receipt_id']}"
    page = client.get(url)
    assert page.status_code == 200 and 'Discard receipt' in page.text
    assert client.get(url + '/export?format=json').json()['recorded_count'] == 1
    root = f'/matters/{matter.slug}/intake-receipts'
    blocked = client.post(root, json={'selection_key': 'e' * 32, 'selection_fingerprint': 'f' * 64,
        'selected_count': 1, 'eligible_indexes': [], 'collection_name': 'Generated new selection'})
    assert blocked.status_code == 409
    assert 'Confirm that you want to discard' in client.post(url + '/discard', data={}).text
    discarded = client.post(url + '/discard', data={'confirm': 'yes'})
    assert discarded.status_code == 200 and 'Receipt discarded.' in discarded.text
    assert client.get(url).status_code == 404
    if bound:
        assert bench.workspace.upload_session_record(matter.matter_id, member, session.upload_session_id).state == 'cancelled'
        assert not any(bench.workspace.active_matter_work_counts(matter.matter_id).values())
    assert selection(client, matter.slug, [descriptor('Generated/new.bin', 4)], [], key='e' * 32)['state'] == 'ready'


def test_owner_cancels_empty_bound_receipt_and_later_upload_cannot_start(workspace):
    from tests.test_intake_receipt_http import descriptor, selection, upload
    client, bench, matter = workspace
    files = [descriptor('Generated/retained.txt', 48)]
    receipt = selection(client, matter.slug, files, [0])
    session = upload(client, matter.slug, receipt, files, [0])
    assert 'intake-receipt-discard' in client.get(receipt['receipt_url']).text
    response = client.post(receipt['receipt_url'] + '/discard', data={'confirm': 'yes'})
    assert response.status_code == 200 and 'Receipt discarded.' in response.text
    assert client.get(receipt['receipt_url']).status_code == 404
    status = client.get(session['status_url'])
    assert status.status_code == 200 and status.json()['state'] == 'cancelled'
    item = session['items'][0]
    response = client.put(item['chunk_url'], content=b'x',
        headers={'Content-Type': 'application/octet-stream', 'X-Upload-Offset': '0'})
    assert response.status_code == 409
    assert not bench.source_store(matter).documents
    assert bench.source_store(matter).resumable_size(item['upload_item_id'], expected_size=48) == 0


@pytest.mark.parametrize('finalized', [False, True])
def test_receipt_with_received_data_remains_available_and_preserves_bytes(workspace, finalized):
    from tests.test_intake_receipt_http import descriptor, selection, upload, put
    client, bench, matter = workspace
    body = b'Generated protected receipt bytes.\n'
    files = [descriptor('Generated/retained.txt', len(body))]
    receipt = selection(client, matter.slug, files, [0])
    session = upload(client, matter.slug, receipt, files, [0])
    item = session['items'][0]
    received = body if finalized else body[:7]
    put(client, item, received)
    if finalized:
        assert client.post(item['finalize_url']).status_code == 200
    assert 'intake-receipt-discard' not in client.get(receipt['receipt_url']).text
    response = client.post(receipt['receipt_url'] + '/discard', data={'confirm': 'yes'})
    assert response.status_code == 200 and 'received data' in response.text
    assert client.get(receipt['receipt_url']).status_code == 200
    store = bench.source_store(matter)
    if finalized:
        document = next(iter(store.documents.values()))
        assert store.source_path(document.document_id).read_bytes() == body
    else:
        assert (store.incoming / store._resumable_name(item['upload_item_id'])).read_bytes() == received


def test_uncommitted_saved_bytes_prevent_discard_and_resume_exactly(workspace):
    from tests.test_intake_receipt_http import descriptor, selection, upload, put
    client, bench, matter = workspace
    body = b'Generated saved bytes before their offset commit.\n'
    files = [descriptor('Generated/retained.txt', len(body))]
    receipt = selection(client, matter.slug, files, [0])
    session = upload(client, matter.slug, receipt, files, [0])
    item = session['items'][0]
    store = bench.source_store(matter)
    store.append_resumable_chunk(item['upload_item_id'], offset=0, expected_size=len(body), chunk=body[:7])
    assert bench.workspace.upload_item(matter.matter_id, ACTOR, session['upload_session_id'], item['upload_item_id']).received_size == 0
    response = client.post(receipt['receipt_url'] + '/discard', data={'confirm': 'yes'})
    assert response.status_code == 200 and 'received data' in response.text
    assert client.get(receipt['receipt_url']).status_code == 200
    assert store.resumable_size(item['upload_item_id'], expected_size=len(body)) == 7
    put(client, item, body[7:], offset=7)
    assert client.post(item['finalize_url']).status_code == 200
    assert store.source_path(next(iter(store.documents))).read_bytes() == body


def test_discard_before_a_delayed_request_body_prevents_any_later_byte_write(workspace):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from fastapi.testclient import TestClient
    from tests.test_intake_receipt_http import descriptor, selection, upload
    client, bench, matter = workspace
    files = [descriptor('Generated/delayed.txt', 48)]
    receipt = selection(client, matter.slug, files, [0])
    session = upload(client, matter.slug, receipt, files, [0])
    item = session['items'][0]
    reading = threading.Event()
    release = threading.Event()

    def body():
        reading.set()
        assert release.wait(8)
        yield b'partial'

    # A separate portal lets the owner request run while this request is
    # awaiting its body, as separate connections do in the application.
    other = TestClient(client.app)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(other.put, item['chunk_url'], content=body(),
                headers={'Content-Type': 'application/octet-stream', 'X-Upload-Offset': '0'})
            try:
                assert reading.wait(5)
                response = client.post(receipt['receipt_url'] + '/discard', data={'confirm': 'yes'})
                assert response.status_code == 200 and 'Receipt discarded.' in response.text
            finally:
                release.set()
            assert future.result(timeout=5).status_code == 409
        store = bench.source_store(matter)
        assert store.resumable_size(item['upload_item_id'], expected_size=48) == 0
        assert client.get(session['status_url']).json()['state'] == 'cancelled'
        assert not store.documents
    finally:
        release.set()
        other.close()


def test_a_chunk_that_arrives_before_discard_keeps_its_receipt_and_saved_bytes(workspace, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from fastapi.testclient import TestClient
    from tests.test_intake_receipt_http import descriptor, selection, upload
    client, bench, matter = workspace
    receipt = selection(client, matter.slug, [descriptor('Generated/arriving.txt', 48)], [0])
    session = upload(client, matter.slug, receipt, [descriptor('Generated/arriving.txt', 48)], [0])
    item = session['items'][0]
    before_commit = threading.Event()
    owner_requested = threading.Event()
    release = threading.Event()
    original_offset = bench.workspace.set_upload_item_offset
    original_store = bench.source_store

    def paused_offset(*args, **kwargs):
        before_commit.set()
        assert release.wait(8)
        return original_offset(*args, **kwargs)

    monkeypatch.setattr(bench.workspace, 'set_upload_item_offset', paused_offset)
    other = TestClient(client.app)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(other.put, item['chunk_url'], content=b'partial',
                headers={'Content-Type': 'application/octet-stream', 'X-Upload-Offset': '0'})
            try:
                assert before_commit.wait(5)
                def owner_store(*args, **kwargs):
                    owner_requested.set()
                    return original_store(*args, **kwargs)
                monkeypatch.setattr(bench, 'source_store', owner_store)
                discard = pool.submit(client.post, receipt['receipt_url'] + '/discard', data={'confirm': 'yes'})
                assert owner_requested.wait(5)
            finally:
                release.set()
            assert writer.result(timeout=5).status_code == 200
            response = discard.result(timeout=5)
            assert response.status_code == 200 and 'received data' in response.text
        assert client.get(receipt['receipt_url']).status_code == 200
        store = original_store(matter)
        assert (store.incoming / store._resumable_name(item['upload_item_id'])).read_bytes() == b'partial'
        assert bench.workspace.upload_item(matter.matter_id, ACTOR, session['upload_session_id'], item['upload_item_id']).received_size == 7
    finally:
        release.set()
        other.close()
