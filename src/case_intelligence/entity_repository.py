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
        where = "matter_id=? AND (display_name LIKE ? ESCAPE '\\' OR aliases_json LIKE ? ESCAPE '\\')"
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

    def add_mention(self, matter_id, actor_id, entity_id, reference, origin):
        names = ('document_id', 'source_version_id', 'source_name', 'location', 'unit_number',
                 'chunk_id', 'excerpt_digest', 'excerpt', 'support_token')
        self.connection.execute(
            'INSERT INTO workbench_entity_mention(mention_id,matter_id,entity_id,' + ','.join(names)
            + ',origin,created_by,created_at) VALUES (' + ','.join('?' for _ in range(15)) + ')',
            ('mention-' + uuid.uuid4().hex, matter_id, entity_id, *(reference[name] for name in names),
             origin, actor_id, self.now()),
        )

    def remove_mention(self, matter_id, entity_id, mention_id):
        cursor = self.connection.execute(
            'DELETE FROM workbench_entity_mention WHERE matter_id=? AND entity_id=? AND mention_id=?',
            (matter_id, entity_id, mention_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(mention_id)

    def record_history(self, matter_id, actor_id, entity_id, action):
        current = self.get(matter_id, entity_id)
        snapshot = dict(current, mentions=self.mentions(matter_id, entity_id))
        self.connection.execute(
            'INSERT INTO workbench_entity_history VALUES (?,?,?,?,?,?,?)',
            (entity_id, matter_id, current['revision'], action, json.dumps(snapshot), actor_id, self.now()),
        )
        self.connection.execute('UPDATE workbench_matter SET updated_at=? WHERE matter_id=?', (self.now(), matter_id))

    def delete(self, matter_id, entity_id):
        self.connection.execute('DELETE FROM workbench_entity WHERE matter_id=? AND entity_id=?', (matter_id, entity_id))
        self.connection.execute('UPDATE workbench_matter SET updated_at=? WHERE matter_id=?', (self.now(), matter_id))

    def export_records(self, matter_id):
        for row in self.connection.execute(
                'SELECT entity_id FROM workbench_entity WHERE matter_id=? ORDER BY entity_id', (matter_id,)):
            entity_id = row[0]
            yield dict(format='recordbench-entity-v1', entity=self.get(matter_id, entity_id),
                       mentions=self.mentions(matter_id, entity_id), history=self.history(matter_id, entity_id),
                       source_support='Retained original-source support; availability is not revalidated in this bundle.')
