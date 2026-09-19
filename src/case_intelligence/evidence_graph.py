"""Bounded, read-only neighborhoods of explicit saved roles and original accounts.

An edge is a reviewer's recorded role or attributed source account. Names,
co-mentions and similarity never create an edge or identify another entity.
"""
import json

from .entity_service import REFERENCE_FIELDS
from .workspace_store import WorkspaceProblem


RECORDS_PER_PAGE = 8
ROLES_PER_RECORD = 20
ACCOUNTS_PER_STANCE = 10
MAX_EXCERPT_CHARS = 6000


class EvidenceGraphRepository:
    """Queries compose with the assertion service's already authorized transaction."""

    def __init__(self, assertion_repository):
        self.connection = assertion_repository.connection

    def center(self, matter_id, entity_id):
        row = self.connection.execute(
            'SELECT entity_id,entity_type,display_name,status,aliases_json,revision '
            'FROM workbench_entity WHERE matter_id=? AND entity_id=?',
            (matter_id, entity_id),
        ).fetchone()
        if row is None:
            raise KeyError(entity_id)
        result = dict(row)
        result['aliases'] = json.loads(result.pop('aliases_json'))
        return result

    def records(self, matter_id, entity_id, page):
        total = self.connection.execute(
            'SELECT COUNT(DISTINCT assertion_id) FROM workbench_assertion_role '
            'WHERE matter_id=? AND entity_id=?', (matter_id, entity_id),
        ).fetchone()[0]
        rows = self.connection.execute(
            'SELECT a.* FROM workbench_assertion a WHERE a.matter_id=? '
            'AND a.assertion_id IN (SELECT r.assertion_id FROM workbench_assertion_role r '
            'WHERE r.matter_id=? AND r.entity_id=?) '
            "ORDER BY (a.sort_date=''),a.sort_date,a.created_at,a.assertion_id LIMIT ? OFFSET ?",
            (matter_id, matter_id, entity_id, RECORDS_PER_PAGE, (page - 1) * RECORDS_PER_PAGE),
        ).fetchall()
        return [dict(row) for row in rows], total

    def roles(self, matter_id, entity_id, assertion_ids):
        placeholders = ','.join('?' for _ in assertion_ids)
        rows = self.connection.execute(
            'WITH ranked AS (SELECT r.*,e.revision AS current_revision,'
            'e.display_name AS current_display_name,e.entity_type AS current_entity_type,'
            'COUNT(*) OVER (PARTITION BY r.assertion_id) AS graph_total,'
            'ROW_NUMBER() OVER (PARTITION BY r.assertion_id '
            'ORDER BY CASE WHEN r.entity_id=? THEN 0 ELSE 1 END,r.created_at,r.role_id) AS graph_rank '
            'FROM workbench_assertion_role r LEFT JOIN workbench_entity e '
            'ON e.matter_id=r.matter_id AND e.entity_id=r.entity_id '
            'WHERE r.matter_id=? AND r.assertion_id IN (' + placeholders + ')) '
            'SELECT * FROM ranked WHERE graph_rank<=? ORDER BY assertion_id,graph_rank',
            (entity_id, matter_id, *assertion_ids, ROLES_PER_RECORD),
        ).fetchall()
        return [dict(row) for row in rows]

    def accounts(self, matter_id, assertion_ids):
        placeholders = ','.join('?' for _ in assertion_ids)
        # A malformed saved excerpt must not cause an unbounded Python read or
        # become apparently valid support after a silent prefix truncation.
        columns = ','.join(
            f'substr(a.excerpt,1,{MAX_EXCERPT_CHARS + 1}) AS excerpt' if name == 'excerpt'
            else 'a.' + name for name in REFERENCE_FIELDS
        )
        rows = self.connection.execute(
            'WITH ranked AS (SELECT a.account_id,a.matter_id,a.assertion_id,a.stance,'
            'a.attributed_to,a.created_by,a.created_at,' + columns + ','
            'COUNT(*) OVER (PARTITION BY a.assertion_id,a.stance) AS graph_total,'
            'ROW_NUMBER() OVER (PARTITION BY a.assertion_id,a.stance '
            'ORDER BY a.created_at,a.account_id) AS graph_rank '
            'FROM workbench_assertion_account a WHERE a.matter_id=? '
            'AND a.assertion_id IN (' + placeholders + ')) '
            'SELECT * FROM ranked WHERE graph_rank<=? ORDER BY assertion_id,stance DESC,graph_rank',
            (matter_id, *assertion_ids, ACCOUNTS_PER_STANCE),
        ).fetchall()
        return [dict(row) for row in rows]


class EvidenceGraphService:
    def __init__(self, assertion_service):
        self.assertions = assertion_service
        self.repository = EvidenceGraphRepository(assertion_service.repository)

    def neighborhood(self, matter_id, actor_id, entity_id, page=1):
        if type(page) is not int or not 1 <= page <= 100000:
            raise WorkspaceProblem('Choose a valid connections page.')
        if not isinstance(entity_id, str) or not entity_id or len(entity_id) > 80:
            raise WorkspaceProblem('Choose a saved entity to explore.')
        entities = self.assertions.entities
        with entities.source_guard(), self.assertions.repository.transaction(matter_id, actor_id) as authorized:
            center = self.repository.center(matter_id, entity_id)
            records, total = self.repository.records(matter_id, entity_id, page)
            grouped = {record['assertion_id']: dict(
                record=record, roles=[], accounts=[], role_total=0, roles_omitted=0,
                account_total=0, accounts_omitted=0,
                account_totals=dict(supporting=0, competing=0),
                account_omissions=dict(supporting=0, competing=0),
                center_identity_state='current',
            ) for record in records}
            if records:
                assertion_ids = list(grouped)
                for role in self.repository.roles(matter_id, entity_id, assertion_ids):
                    row = grouped[role['assertion_id']]
                    row['role_total'] = role.pop('graph_total')
                    role.pop('graph_rank')
                    state = ('missing' if role['current_revision'] is None else
                             'current' if role['current_revision'] == role['entity_revision'] else 'changed')
                    role['identity_state'] = state
                    role['traversable'] = state == 'current'
                    if role['entity_id'] == entity_id and state != 'current':
                        row['center_identity_state'] = state
                    row['roles'].append(role)
                accounts = self.repository.accounts(matter_id, assertion_ids)
                if any(len(account['excerpt']) > MAX_EXCERPT_CHARS for account in accounts):
                    raise WorkspaceProblem('Saved support exceeds the connections excerpt limit. Open the complete record to inspect it.')
                for account in accounts:
                    row = grouped[account['assertion_id']]
                    row['account_totals'][account['stance']] = account.pop('graph_total')
                    account.pop('graph_rank')
                # One batch retains each reference position, even when tokens
                # repeat with different saved metadata. No history is loaded.
                available = entities.validate_references(accounts)
                for index, account in enumerate(accounts):
                    account['available'] = index in available
                    grouped[account['assertion_id']]['accounts'].append(account)
            for row in grouped.values():
                row['roles_omitted'] = row['role_total'] - len(row['roles'])
                for stance, count in row['account_totals'].items():
                    shown = sum(account['stance'] == stance for account in row['accounts'])
                    row['account_omissions'][stance] = count - shown
                row['account_total'] = sum(row['account_totals'].values())
                row['accounts_omitted'] = sum(row['account_omissions'].values())
            # Keep direct service reads fenced too; HTTP adapters additionally
            # reauthorize after constructing their response.
            authorized.entities.authorize(matter_id, actor_id)
            return dict(
                center=center, records=list(grouped.values()), page=page,
                pages=max(1, (total + RECORDS_PER_PAGE - 1) // RECORDS_PER_PAGE),
                total_records=total, shown_records=len(records), records_omitted=total - len(records),
                limits=dict(records=RECORDS_PER_PAGE, roles_per_record=ROLES_PER_RECORD,
                            accounts_per_record=ACCOUNTS_PER_STANCE * 2,
                            accounts_per_stance=ACCOUNTS_PER_STANCE),
            )
