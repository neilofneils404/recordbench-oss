"""Entity persistence inside the control store's authorized unit of work.

No independent connection, implicit transaction, or name-based identity lookup.
The service owns the source guard; this repository owns the workspace transaction.
"""
from contextlib import contextmanager
import json
import uuid

from .workspace_store import WorkspaceProblem


class EntityEditConflict(WorkspaceProblem):
    pass


class EntityRepository:
    def __init__(self, *, connection, lock, authorize, now):
        self.connection = connection
        self.lock = lock
        self.authorize = authorize
        self.now = now

    @contextmanager
    def transaction(self, matter_id, actor_id):
        with self.lock, self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            self.authorize(matter_id, actor_id)
            yield self

    @staticmethod
    def record(row):
        result = dict(row)
        result['aliases'] = json.loads(result.pop('aliases_json'))
        result['notebook_snapshot'] = json.loads(result.pop('notebook_snapshot_json') or 'null')
        return result

    def get(self, matter_id, entity_id):
        row = self.connection.execute(
            'SELECT * FROM workbench_entity WHERE matter_id=? AND entity_id=?',
            (matter_id, entity_id),
        ).fetchone()
        if row is None:
            raise KeyError(entity_id)
        return self.record(row)

    def list(self, matter_id, query='', page=1):
        # Escape wildcard characters: name/alias search never changes identities.
        like = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        where = "matter_id=? AND (display_name LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM json_each(aliases_json) WHERE value LIKE ? ESCAPE '\\'))"
        params = (matter_id, like, like)
        total = self.connection.execute('SELECT COUNT(*) FROM workbench_entity WHERE ' + where, params).fetchone()[0]
        rows = self.connection.execute(
            'SELECT * FROM workbench_entity WHERE ' + where + ' ORDER BY display_name,entity_id LIMIT 50 OFFSET ?',
            (*params, (page - 1) * 50),
        ).fetchall()
        return [self.record(row) for row in rows], total

    def mentions(self, matter_id, entity_id):
        return [dict(row) for row in self.connection.execute(
            'SELECT * FROM workbench_entity_mention WHERE matter_id=? AND entity_id=? ORDER BY created_at,mention_id',
            (matter_id, entity_id),
        )]

    def history(self, matter_id, entity_id):
        return [dict(row) for row in self.connection.execute(
            'SELECT * FROM workbench_entity_history WHERE matter_id=? AND entity_id=? ORDER BY revision DESC',
            (matter_id, entity_id),
        )]

    def check_revision(self, matter_id, entity_id, expected_revision):
        current = self.get(matter_id, entity_id)
        if current['revision'] != expected_revision:
            raise EntityEditConflict('This entity changed since you opened it. Compare the saved version with your unsaved work before saving again.')
        return current

    def imported(self, matter_id, item_id):
        row = self.connection.execute(
            'SELECT entity_id FROM workbench_entity WHERE matter_id=? AND notebook_item_id=?',
            (matter_id, item_id),
        ).fetchone()
        return self.get(matter_id, row[0]) if row else None

    def create(self, matter_id, actor_id, fields, *, notebook=None):
        entity_id = 'entity-' + uuid.uuid4().hex
        now = self.now()
        self.connection.execute(
            'INSERT INTO workbench_entity(entity_id,matter_id,entity_type,display_name,status,aliases_json,origin,'
            'notebook_item_id,notebook_snapshot_json,created_by,created_at,updated_by,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (entity_id, matter_id, fields['entity_type'], fields['display_name'], fields['status'],
             json.dumps(fields['aliases']), 'notebook' if notebook else 'manual',
             notebook['item_id'] if notebook else None, json.dumps(notebook) if notebook else None,
             actor_id, now, actor_id, now),
        )
        return self.get(matter_id, entity_id)

    def save(self, matter_id, actor_id, entity_id, fields):
        self.connection.execute(
            'UPDATE workbench_entity SET entity_type=?,display_name=?,status=?,aliases_json=?,'
            'revision=revision+1,updated_by=?,updated_at=? WHERE matter_id=? AND entity_id=?',
            (fields['entity_type'], fields['display_name'], fields['status'], json.dumps(fields['aliases']),
             actor_id, self.now(), matter_id, entity_id),
        )

    def has_mention(self, matter_id, entity_id, support_token):
        return self.connection.execute(
            'SELECT 1 FROM workbench_entity_mention WHERE matter_id=? AND entity_id=? AND support_token=?',
            (matter_id, entity_id, support_token),
        ).fetchone() is not None

    def add_mention(self, matter_id, actor_id, entity_id, reference, origin):
        names = ('document_id', 'source_version_id', 'source_name', 'location', 'unit_number',
                 'chunk_id', 'excerpt_digest', 'excerpt', 'support_token')
        mention_id = 'mention-' + uuid.uuid4().hex
        self.connection.execute(
            'INSERT INTO workbench_entity_mention(mention_id,matter_id,entity_id,' + ','.join(names)
            + ',origin,created_by,created_at) VALUES (' + ','.join('?' for _ in range(15)) + ')',
            (mention_id, matter_id, entity_id, *(reference[name] for name in names),
             origin, actor_id, self.now()),
        )

        return dict(self.connection.execute(
            'SELECT * FROM workbench_entity_mention WHERE mention_id=?', (mention_id,)).fetchone())

    def remove_mention(self, matter_id, entity_id, mention_id):
        removed = self.connection.execute(
            'SELECT * FROM workbench_entity_mention WHERE matter_id=? AND entity_id=? AND mention_id=?',
            (matter_id, entity_id, mention_id),
        ).fetchone()
        if removed is None:
            raise KeyError(mention_id)
        cursor = self.connection.execute(
            'DELETE FROM workbench_entity_mention WHERE matter_id=? AND entity_id=? AND mention_id=?',
            (matter_id, entity_id, mention_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(mention_id)
        return dict(removed)

    def record_history(self, matter_id, actor_id, entity_id, action, *, added_mentions=(), removed_mentions=()):
        current = self.get(matter_id, entity_id)
        # Store each mention only at addition/removal, never in every later edit.
        # Old full snapshots remain readable; new records describe explicit deltas.
        snapshot = dict(current, history_format=2, added_mentions=list(added_mentions),
                        removed_mentions=list(removed_mentions))
        if action not in ('created', 'notebook imported'):
            snapshot.pop('notebook_snapshot', None)
        self.connection.execute(
            'INSERT INTO workbench_entity_history VALUES (?,?,?,?,?,?,?)',
            (entity_id, matter_id, current['revision'], action, json.dumps(snapshot), actor_id, self.now()),
        )
        self.connection.execute('UPDATE workbench_matter SET updated_at=? WHERE matter_id=?', (self.now(), matter_id))

    def delete(self, matter_id, entity_id):
        self.connection.execute("DELETE FROM workbench_entity_reconciliation WHERE matter_id=? AND "
            "(json_extract(before_json,'$.source.entity_id')=? OR json_extract(before_json,'$.target.entity_id')=?)",
            (matter_id, entity_id, entity_id))
        self.connection.execute('DELETE FROM workbench_entity WHERE matter_id=? AND entity_id=?', (matter_id, entity_id))
        self.connection.execute('UPDATE workbench_matter SET updated_at=? WHERE matter_id=?', (self.now(), matter_id))

    def export_records(self, matter_id):
        for row in self.connection.execute(
                'SELECT entity_id FROM workbench_entity WHERE matter_id=? ORDER BY entity_id', (matter_id,)):
            entity_id = row[0]
            yield dict(format='recordbench-entity-v1', entity=self.get(matter_id, entity_id),
                       mentions=self.mentions(matter_id, entity_id), history=self.history(matter_id, entity_id),
                       reconciliations=self.reconciliations(matter_id, entity_id),
                       source_support='Retained original-source support; availability is not revalidated in this bundle.')

    def discovery_runs(self, matter_id, page=1):
        return [dict(row) for row in self.connection.execute(
            'SELECT r.run_id,r.state,r.created_at FROM workbench_review_run r '
            'JOIN workbench_text_review t ON t.run_id=r.run_id WHERE r.matter_id=? ORDER BY r.created_at DESC,r.run_id LIMIT 21 OFFSET ?', (matter_id, (page - 1) * 20))]

    def require_discovery_run(self, matter_id, run_id):
        if not self.connection.execute('SELECT 1 FROM workbench_review_run r JOIN workbench_text_review t '
                'ON t.run_id=r.run_id WHERE r.matter_id=? AND r.run_id=?', (matter_id, run_id)).fetchone():
            raise KeyError(run_id)

    def discovery_pending(self, matter_id, run_id, version, limit, retry):
        return [dict(row) for row in self.connection.execute(
            "SELECT ? AS matter_id,u.run_id,u.document_id,s.source_version_id,u.unit_ordinal,u.unit_digest,"
            "? AS extractor_version,COALESCE(d.state,'pending') AS state,COALESCE(d.note,'') AS note "
            "FROM workbench_text_review_source s JOIN workbench_text_review_unit u "
            "ON u.run_id=s.run_id AND u.document_id=s.document_id "
            "LEFT JOIN workbench_entity_discovery_unit d ON d.matter_id=? AND d.run_id=u.run_id "
            "AND d.document_id=u.document_id AND d.unit_ordinal=u.unit_ordinal AND d.extractor_version=? "
            "WHERE s.run_id=? AND s.inventory_sealed=1 AND "
            "((? AND d.state='failed') OR (NOT ? AND (d.state IS NULL OR d.state='pending'))) "
            "ORDER BY u.document_id,u.unit_ordinal LIMIT ?",
            (matter_id, version, matter_id, version, run_id, retry, retry, limit))]

    def seed_discovery_unit(self, unit):
        self.connection.execute("INSERT OR IGNORE INTO workbench_entity_discovery_unit "
            "(matter_id,run_id,document_id,source_version_id,unit_ordinal,unit_digest,extractor_version,state) "
            "VALUES (?,?,?,?,?,?,?,'pending')",
            tuple(unit[key] for key in ('matter_id','run_id','document_id','source_version_id',
                                       'unit_ordinal','unit_digest','extractor_version')))

    def discovery_storage_bytes(self, matter_id):
        # A logical payload budget, with per-row allowance. Include human records
        # and retained history so repeated extractor versions cannot reset it.
        total = 0
        for table in ('workbench_entity', 'workbench_entity_mention', 'workbench_entity_history',
                      'workbench_entity_discovery_seen', 'workbench_entity_discovery_unit',
                      'workbench_entity_reconciliation'):
            columns = [row[1] for row in self.connection.execute(f'PRAGMA table_info({table})')]
            sizes = '+'.join(f'COALESCE(length(CAST("{column}" AS BLOB)),0)' for column in columns)
            total += self.connection.execute(f'SELECT COALESCE(SUM(256+{sizes}),0) FROM {table} WHERE matter_id=?',
                (matter_id,)).fetchone()[0]
        return total

    def has_discovery_receipt(self, matter_id, key):
        return self.connection.execute('SELECT 1 FROM workbench_entity_discovery_seen WHERE matter_id=? AND occurrence_key=?',
            (matter_id, key)).fetchone() is not None

    def discovery_source_current(self, matter_id, unit):
        return self.connection.execute(
            "SELECT 1 FROM workbench_text_review_source s JOIN workbench_source_catalog c "
            "ON c.document_id=s.document_id AND c.matter_id=? WHERE s.run_id=? AND s.document_id=? "
            "AND s.state!='invalidated' AND s.inventory_sealed=1 AND c.source_state='ready' "
            "AND c.version_id=s.source_version_id AND c.content_basis_digest=s.source_basis_digest",
            (matter_id, unit['run_id'], unit['document_id'])).fetchone() is not None

    def discovery_claimable(self, matter_id, unit, retry):
        row = self.connection.execute(
            'SELECT state FROM workbench_entity_discovery_unit WHERE matter_id=? AND run_id=? AND document_id=? '
            'AND unit_ordinal=? AND extractor_version=?',
            (matter_id, unit['run_id'], unit['document_id'], unit['unit_ordinal'], unit['extractor_version'])).fetchone()
        return (row is not None and row[0] == 'failed') if retry else (row is None or row[0] == 'pending')

    def discovery_state(self, unit, state, note):
        self.connection.execute('UPDATE workbench_entity_discovery_unit SET state=?,note=? WHERE matter_id=? '
            'AND run_id=? AND document_id=? AND unit_ordinal=? AND extractor_version=?',
            (state, note, unit['matter_id'], unit['run_id'], unit['document_id'], unit['unit_ordinal'], unit['extractor_version']))

    def discovery_coverage(self, matter_id, run_id, version, *, page=1, source_page=1, limit=50):
        self.require_discovery_run(matter_id, run_id)
        current = "(s.state!='invalidated' AND c.source_state='ready' AND c.version_id=s.source_version_id AND c.content_basis_digest=s.source_basis_digest)"
        source_from = (' FROM workbench_text_review_source s LEFT JOIN workbench_source_catalog c '
                       'ON c.document_id=s.document_id AND c.matter_id=? WHERE s.run_id=?')
        source_state = f"CASE WHEN s.inventory_sealed=1 AND NOT COALESCE({current},0) THEN 'invalidated' ELSE s.state END"
        source_counts = {row[0]: row[1] for row in self.connection.execute(
            'SELECT ' + source_state + ',COUNT(*)' + source_from + ' GROUP BY 1', (matter_id, run_id))}
        uninventoried = self.connection.execute('SELECT COUNT(*)' + source_from + ' AND s.inventory_sealed=0',
            (matter_id, run_id)).fetchone()[0]
        sources = [dict(row) for row in self.connection.execute(
            'SELECT s.document_id,s.source_name,s.inventory_sealed,s.unit_count,' + source_state + ' AS state'
            + source_from + ' ORDER BY s.document_id LIMIT ? OFFSET ?',
            (matter_id, run_id, limit, (source_page - 1) * 50))] if limit else []
        # Count in SQLite; only materialize the requested page of unit metadata.
        cte = ("WITH coverage AS (SELECT s.run_id,s.document_id,s.source_name,s.source_version_id,"
            "u.unit_ordinal,u.unit_digest,CASE WHEN NOT COALESCE(" + current + ",0) THEN 'invalidated' "
            "ELSE COALESCE(d.state,'pending') END AS state,"
            "CASE WHEN NOT COALESCE(" + current + ",0) THEN 'Frozen source changed or is unavailable.' "
            "ELSE COALESCE(d.note,'Not yet queued for discovery.') END AS note "
            "FROM workbench_text_review_source s JOIN workbench_text_review_unit u "
            "ON u.run_id=s.run_id AND u.document_id=s.document_id "
            "LEFT JOIN workbench_source_catalog c ON c.document_id=s.document_id AND c.matter_id=? "
            "LEFT JOIN workbench_entity_discovery_unit d ON d.matter_id=? AND d.run_id=s.run_id "
            "AND d.document_id=s.document_id AND d.unit_ordinal=u.unit_ordinal AND d.extractor_version=? "
            "WHERE s.run_id=? AND s.inventory_sealed=1) ")
        params = (matter_id, matter_id, version, run_id)
        counts = dict.fromkeys(('pending','processed','failed','invalidated'), 0)
        counts.update({row[0]: row[1] for row in self.connection.execute(
            cte + 'SELECT state,COUNT(*) FROM coverage GROUP BY state', params)})
        units = [dict(row) for row in self.connection.execute(
            cte + 'SELECT * FROM coverage ORDER BY document_id,unit_ordinal LIMIT ? OFFSET ?',
            (*params, limit, (page - 1) * 50))] if limit else []
        return dict(run_id=run_id, extractor_version=version, units=units, sources=sources, counts=counts,
            unit_total=sum(counts.values()), source_total=sum(source_counts.values()),
            source_counts=source_counts, uninventoried=uninventoried, page=page, source_page=source_page)

    def discovery_seen(self, matter_id, key):
        cursor = self.connection.execute('INSERT OR IGNORE INTO workbench_entity_discovery_seen VALUES (?,?)', (matter_id, key))
        return cursor.rowcount == 0

    def mark_extracted(self, matter_id, entity_id, version):
        self.connection.execute("UPDATE workbench_entity SET origin='extraction',extractor_version=? WHERE matter_id=? AND entity_id=?", (version, matter_id, entity_id))

    def annotate_occurrence(self, matter_id, mention_id, key, version, occurrence):
        self.connection.execute('UPDATE workbench_entity_mention SET occurrence_key=?,extractor_version=?,surface_text=?,'
            'start_offset=?,end_offset=?,date_json=?,review_status=? WHERE matter_id=? AND mention_id=?',
            (key, version, occurrence.label, occurrence.start, occurrence.end,
             json.dumps(dict(kind=occurrence.kind, date=occurrence.date)), 'suggested', matter_id, mention_id))
        return dict(self.connection.execute('SELECT * FROM workbench_entity_mention WHERE matter_id=? AND mention_id=?', (matter_id, mention_id)).fetchone())

    def candidate_page(self, matter_id, entity_id, page):
        entity = self.get(matter_id, entity_id)
        rows = self.connection.execute(
            "SELECT e.* FROM workbench_entity e WHERE e.matter_id=? AND e.entity_id!=? "
            "AND NOT EXISTS (SELECT 1 FROM workbench_entity_reconciliation r WHERE r.matter_id=e.matter_id "
            "AND r.action='reject' AND r.undone=0 AND "
            "((json_extract(r.before_json,'$.source.entity_id')=? AND json_extract(r.before_json,'$.target.entity_id')=e.entity_id) "
            "OR (json_extract(r.before_json,'$.target.entity_id')=? AND json_extract(r.before_json,'$.source.entity_id')=e.entity_id))) "
            "ORDER BY e.display_name,e.entity_id LIMIT 51 OFFSET ?",
            (matter_id, entity_id, entity_id, entity_id, (page - 1) * 50))
        return entity, [self.record(row) for row in rows]

    @staticmethod
    def score_candidates(entity, pool):
        from difflib import SequenceMatcher
        labels = {value.casefold() for value in [entity['display_name'], *entity['aliases']]}
        result = []
        for other in pool:
            other_labels = {value.casefold() for value in [other['display_name'], *other['aliases']]}
            # Exact alias overlap needs no Cartesian fuzzy comparison. Fuzzy
            # matching is confined to one display-name pair per identity.
            score = 1.0 if labels & other_labels else SequenceMatcher(
                None, entity['display_name'].casefold(), other['display_name'].casefold()).ratio()
            if score >= .72:
                result.append(dict(other, match_score=score))
        return sorted(result, key=lambda row: (-row['match_score'], row['entity_id']))

    def reconciliations(self, matter_id, entity_id):
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM workbench_entity_reconciliation WHERE matter_id=? AND "
            "(json_extract(before_json,'$.source.entity_id')=? OR json_extract(before_json,'$.target.entity_id')=?) "
            "ORDER BY created_at DESC,operation_id DESC", (matter_id, entity_id, entity_id))]

    def move_mentions(self, matter_id, source_id, target_id, mention_ids):
        mentions = {row['mention_id']: row for row in self.mentions(matter_id, source_id)}
        if not set(mention_ids) <= mentions.keys():
            raise WorkspaceProblem('A selected mention is no longer on this identity.')
        for mention_id in mention_ids:
            self.connection.execute('UPDATE workbench_entity_mention SET entity_id=? WHERE matter_id=? AND entity_id=? AND mention_id=?',
                (target_id, matter_id, source_id, mention_id))
        return [mentions[key] for key in mention_ids]

    def save_reconciliation(self, matter_id, actor_id, action, before, after):
        operation_id = 'reconcile-' + uuid.uuid4().hex
        self.connection.execute('INSERT INTO workbench_entity_reconciliation '
            '(operation_id,matter_id,action,before_json,after_json,actor_id,created_at) VALUES (?,?,?,?,?,?,?)',
            (operation_id, matter_id, action, json.dumps(before), json.dumps(after), actor_id, self.now()))
        return operation_id

    def get_reconciliation(self, matter_id, operation_id):
        row = self.connection.execute('SELECT * FROM workbench_entity_reconciliation WHERE matter_id=? AND operation_id=?',
            (matter_id, operation_id)).fetchone()
        if row is None:
            raise KeyError(operation_id)
        return dict(row)

    def undo_reconciliation(self, matter_id, operation_id):
        self.connection.execute('UPDATE workbench_entity_reconciliation SET undone=1 WHERE matter_id=? AND operation_id=?',
            (matter_id, operation_id))

    def discovery_export(self, matter_id):
        return dict(format='recordbench-entity-discovery-v1',
            source_support='Retained frozen coverage; current source availability is not revalidated in this bundle.',
            sources=[dict(row) for row in self.connection.execute(
                'SELECT s.* FROM workbench_text_review_source s JOIN workbench_review_run r ON r.run_id=s.run_id WHERE r.matter_id=?', (matter_id,))],
            coverage=[dict(row) for row in self.connection.execute('SELECT * FROM workbench_entity_discovery_unit WHERE matter_id=?', (matter_id,))],
            occurrence_tombstones=[row[0] for row in self.connection.execute('SELECT occurrence_key FROM workbench_entity_discovery_seen WHERE matter_id=?', (matter_id,))],
            reconciliations=[dict(row) for row in self.connection.execute('SELECT * FROM workbench_entity_reconciliation WHERE matter_id=?', (matter_id,))])

    def review_mention(self, matter_id, entity_id, mention_id, status):
        cursor = self.connection.execute('UPDATE workbench_entity_mention SET review_status=? WHERE matter_id=? AND entity_id=? AND mention_id=?',
            (status, matter_id, entity_id, mention_id))
        if cursor.rowcount != 1:
            raise KeyError(mention_id)
