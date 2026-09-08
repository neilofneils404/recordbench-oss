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
    assert 'Discard unfinished receipt' in page.text
    discarded = client.post(first['receipt_url'] + '/discard', data={})
    assert discarded.status_code == 200 and 'Confirm that you want to discard' in discarded.text
    assert client.get(first['receipt_url']).status_code == 200
    discarded = client.post(first['receipt_url'] + '/discard', data={'confirm': 'yes'})
    assert discarded.status_code == 200 and 'Unfinished receipt discarded.' in discarded.text
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
