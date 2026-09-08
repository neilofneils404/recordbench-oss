"""Atomic metadata admission and deliberate owner cleanup of receipts without uploads."""
from concurrent.futures import ThreadPoolExecutor

import pytest

import case_intelligence.intake_receipts as module
from case_intelligence.intake_receipts import IntakeReceipts
from case_intelligence.workspace_store import WorkspaceProblem, WorkspaceStore
from tests.test_intake_receipts import OWNER, MEMBER, append, create, descriptor, ready, seed


def limits(monkeypatch, scope, value):
    configured = {key: (10_000, 1_000_000, 128 * 1024 * 1024)
                  for key in ('matter', 'actor', 'workspace')}
    configured[scope] = value
    monkeypatch.setattr(module, 'RECEIPT_LIMITS', configured, raising=False)


@pytest.mark.parametrize('scope', ['matter', 'actor', 'workspace'])
def test_creation_limit_reserves_selected_rows_before_any_batch(tmp_path, monkeypatch, scope):
    w, m, receipts = seed(tmp_path)
    try:
        limits(monkeypatch, scope, (100, 3, 1024 * 1024))
        first = create(receipts, m, 2, (), key='1' * 32)
        second_matter = m if scope == 'matter' else w.create_matter('Generated second matter', '', MEMBER if scope == 'workspace' else OWNER)
        with pytest.raises(WorkspaceProblem, match='receipt'):
            if scope == 'workspace':
                receipts.create(second_matter.matter_id, MEMBER, selection_key='2' * 32,
                    selection_fingerprint='b' * 64, selected_count=2, eligible_indexes=[], collection_name='Generated second selection')
            else:
                create(receipts, second_matter, 2, (), key='2' * 32)
        assert w.connection.execute('SELECT count(*) FROM workbench_intake_receipt').fetchone()[0] == 1
        assert create(receipts, m, 2, (), key='1' * 32)['receipt_id'] == first['receipt_id']
    finally:
        w.close()


def test_receipt_count_limit_preserves_existing_complete_export(tmp_path, monkeypatch):
    w, m, receipts = seed(tmp_path)
    try:
        limits(monkeypatch, 'matter', (2, 100, 1024 * 1024))
        create(receipts, m, 1, (), key='1' * 32)
        create(receipts, m, 1, (), key='2' * 32)
        with pytest.raises(WorkspaceProblem, match='receipt'):
            create(receipts, m, 1, (), key='3' * 32)
        assert len(receipts.export(m.matter_id, OWNER)) == 2
    finally:
        w.close()


@pytest.mark.parametrize('scope', ['matter', 'actor', 'workspace'])
def test_byte_limit_rejects_whole_batch_without_losing_previous_rows(tmp_path, monkeypatch, scope):
    w, m, receipts = seed(tmp_path)
    try:
        receipt = create(receipts, m, 3, ())
        append(receipts, m, receipt, [descriptor('Generated/first.txt')], states=['unsupported'])
        limits(monkeypatch, scope, (100, 100, 1))
        # Exact retries consume no additional space even after admission is full.
        append(receipts, m, receipt, [descriptor('Generated/first.txt')], states=['unsupported'])
        with pytest.raises(WorkspaceProblem, match='receipt'):
            append(receipts, m, receipt, [descriptor('Generated/second.txt'), descriptor('Generated/third.txt')],
                start=1, states=['unsupported', 'unsupported'])
        assert receipts.get(m.matter_id, OWNER, receipt['receipt_id'])['recorded_count'] == 1
    finally:
        w.close()


def test_distinct_database_connections_cannot_race_past_creation_limit(tmp_path, monkeypatch):
    w, m, _ = seed(tmp_path)
    limits(monkeypatch, 'matter', (1, 100, 1024 * 1024))
    w.close()

    def attempt(key):
        local = WorkspaceStore(tmp_path / 'workspace.sqlite')
        try:
            try:
                create(IntakeReceipts(local), m, 1, (), key=key * 32)
                return 'created'
            except WorkspaceProblem:
                return 'full'
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ['1', '2'])) == ['created', 'full']


def test_owner_discard_is_confirmed_without_uploads_and_releases_capacity(tmp_path, monkeypatch):
    w, m, receipts = seed(tmp_path)
    try:
        limits(monkeypatch, 'matter', (1, 100, 1024 * 1024))
        receipt = receipts.create(m.matter_id, MEMBER, selection_key='a' * 32,
            selection_fingerprint='b' * 64, selected_count=1, eligible_indexes=[], collection_name='Generated unfinished selection')
        with pytest.raises(WorkspaceProblem, match='Confirm'):
            receipts.discard(m.matter_id, OWNER, receipt['receipt_id'], confirmed=False)
        with pytest.raises(KeyError):
            receipts.discard(m.matter_id, MEMBER, receipt['receipt_id'], confirmed=True)
        receipts.discard(m.matter_id, OWNER, receipt['receipt_id'], confirmed=True)
        assert receipts.recent(m.matter_id, OWNER) == []
        finished = ready(receipts, m)
        receipts.discard(m.matter_id, OWNER, finished['receipt_id'], confirmed=True)
        assert receipts.recent(m.matter_id, OWNER) == []
    finally:
        w.close()
