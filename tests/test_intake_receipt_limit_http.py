"""Receipt admission, final export and owner cleanup through normal HTTP routes."""
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


def test_owner_recovers_capacity_after_member_seals_skips_and_is_revoked(workspace, monkeypatch):
    from case_intelligence.intake_receipts import IntakeReceipts
    from tests.test_intake_receipt_http import descriptor, selection
    client, bench, matter = workspace
    member = 'generated-selection-member'
    bench.workspace.upsert_principal('test', member, 'Generated member', member, preferred_principal_id=member)
    bench.workspace.add_member(matter.matter_id, member, ACTOR)
    receipts = IntakeReceipts(bench.workspace)
    limits(monkeypatch, 'matter', (1, 3, 1024 * 1024))
    receipt = receipts.create(matter.matter_id, member, selection_key='c' * 32,
        selection_fingerprint='d' * 64, selected_count=1, eligible_indexes=[], collection_name='Generated skips')
    receipts.append(matter.matter_id, member, receipt['receipt_id'], start=0,
        files=[descriptor('Generated/opaque.bin', 4)], reviewed_states=['unsupported'],
        document_limit=1024, media_limit=2048, malware_scan_mode='off', scanner_ready=True)
    receipts.seal(matter.matter_id, member, receipt['receipt_id'])
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
    assert selection(client, matter.slug, [descriptor('Generated/new.bin', 4)], [], key='e' * 32)['state'] == 'ready'


def test_receipt_with_upload_binding_cannot_be_discarded_even_before_bytes(workspace):
    from tests.test_intake_receipt_http import descriptor, selection, upload
    client, bench, matter = workspace
    files = [descriptor('Generated/retained.txt', 48)]
    receipt = selection(client, matter.slug, files, [0])
    session = upload(client, matter.slug, receipt, files, [0])
    assert 'intake-receipt-discard' not in client.get(receipt['receipt_url']).text
    response = client.post(receipt['receipt_url'] + '/discard', data={'confirm': 'yes'})
    assert response.status_code == 200 and 'Receipts linked to uploads' in response.text
    assert client.get(receipt['receipt_url']).status_code == 200
    assert client.get(session['status_url']).status_code == 200
