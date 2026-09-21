"""Bounded projections on the existing authorized control-store connection."""
import json

from .entity_service import REFERENCE_FIELDS


ENTITIES_PER_PAGE = 8
ASSERTIONS_PER_PAGE = 6
REFERENCES_PER_GROUP = 2
MAX_EXCERPT_CHARS = 6000


class MatterKnowledgeRepository:
    def __init__(self, assertion_repository):
        self.connection = assertion_repository.connection

    def _page(self, matter_id, page, *, table, columns, ordering, limit):
        # Identifiers here are fixed by the two callers, never request values.
        total = self.connection.execute(
            f'SELECT COUNT(*) FROM {table} WHERE matter_id=?', (matter_id,)
        ).fetchone()[0]
        pages = max(1, (total + limit - 1) // limit)
        page = min(page, pages)
        rows = self.connection.execute(
            f'SELECT {columns} FROM {table} WHERE matter_id=? ORDER BY {ordering} LIMIT ? OFFSET ?',
            (matter_id, limit, (page - 1) * limit),
        ).fetchall()
        return dict(items=[dict(row) for row in rows], total=total, page=page,
                    pages=pages, omitted=total - len(rows), limit=limit)

    def entities(self, matter_id, page):
        result = self._page(matter_id, page, table='workbench_entity',
            columns='entity_id,entity_type,display_name,aliases_json,status,revision',
            ordering='display_name,entity_id', limit=ENTITIES_PER_PAGE)
        for row in result['items']:
            row['aliases'] = json.loads(row.pop('aliases_json'))
        return result

    def assertions(self, matter_id, page):
        return self._page(matter_id, page, table='workbench_assertion',
            columns='assertion_id,record_type,title,statement,raw_date,date_uncertainty,sort_date,status,revision',
            ordering="(sort_date=''),sort_date,created_at,assertion_id", limit=ASSERTIONS_PER_PAGE)

    def references(self, matter_id, identifiers, *, accounts=False):
        if not identifiers:
            return []
        table = 'workbench_assertion_account' if accounts else 'workbench_entity_mention'
        parent = 'assertion_id' if accounts else 'entity_id'
        identifier = 'account_id' if accounts else 'mention_id'
        group = parent + (',stance' if accounts else '')
        extras = 'stance,attributed_to' if accounts else 'review_status'
        columns = ','.join(
            f'substr(excerpt,1,{MAX_EXCERPT_CHARS + 1}) AS excerpt' if name == 'excerpt'
            else name for name in REFERENCE_FIELDS
        )
        placeholders = ','.join('?' for _ in identifiers)
        rows = self.connection.execute(
            f'WITH ranked AS (SELECT {parent},{identifier},{extras},{columns},'
            f'COUNT(*) OVER (PARTITION BY {group}) AS reference_total,'
            f'ROW_NUMBER() OVER (PARTITION BY {group} ORDER BY created_at,{identifier}) AS reference_rank '
            f'FROM {table} WHERE matter_id=? AND {parent} IN ({placeholders})) '
            f'SELECT * FROM ranked WHERE reference_rank<=? ORDER BY {group},reference_rank',
            (matter_id, *identifiers, REFERENCES_PER_GROUP),
        ).fetchall()
        return [dict(row) for row in rows]
