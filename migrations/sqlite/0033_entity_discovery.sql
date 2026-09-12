-- Caller executes the migration atomically while writers are stopped.
-- Rebuild the constrained tables together; preserve every original ID and row.
CREATE TEMP TABLE entity_migration_backup AS SELECT * FROM workbench_entity;
CREATE TEMP TABLE mention_migration_backup AS SELECT * FROM workbench_entity_mention;
CREATE TEMP TABLE history_migration_backup AS SELECT * FROM workbench_entity_history;
DROP TABLE workbench_entity_history;
DROP TABLE workbench_entity_mention;
DROP TABLE workbench_entity;
CREATE TABLE workbench_entity (
    entity_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('person', 'place', 'thing', 'organization', 'identifier', 'date')),
    display_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('suggested', 'needs_review', 'confirmed', 'disputed', 'dismissed')),
    aliases_json TEXT NOT NULL DEFAULT '[]',
    origin TEXT NOT NULL CHECK (origin IN ('manual', 'notebook', 'extraction')),
    notebook_item_id TEXT,
    notebook_snapshot_json TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, entity_id),
    UNIQUE (matter_id, notebook_item_id)
);
CREATE INDEX workbench_entity_matter_idx
    ON workbench_entity(matter_id, display_name, entity_id);

CREATE TABLE workbench_entity_mention (
    mention_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    location TEXT NOT NULL,
    unit_number INTEGER NOT NULL CHECK (unit_number > 0),
    chunk_id TEXT NOT NULL,
    excerpt_digest TEXT NOT NULL CHECK (length(excerpt_digest) = 64),
    excerpt TEXT NOT NULL,
    support_token TEXT NOT NULL CHECK (length(support_token) = 40),
    origin TEXT NOT NULL CHECK (origin IN ('manual', 'notebook', 'extraction')),
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    FOREIGN KEY (matter_id, entity_id) REFERENCES workbench_entity(matter_id, entity_id) ON DELETE CASCADE
);
CREATE INDEX workbench_entity_mention_source_idx
    ON workbench_entity_mention(matter_id, document_id, source_version_id);

CREATE TABLE workbench_entity_history (
    entity_id TEXT NOT NULL,
    matter_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    action TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    actor_id TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (entity_id, revision),
    FOREIGN KEY (matter_id, entity_id) REFERENCES workbench_entity(matter_id, entity_id) ON DELETE CASCADE
);

INSERT INTO workbench_entity SELECT * FROM entity_migration_backup;
INSERT INTO workbench_entity_mention SELECT * FROM mention_migration_backup;
INSERT INTO workbench_entity_history SELECT * FROM history_migration_backup;
DROP TABLE entity_migration_backup;
DROP TABLE mention_migration_backup;
DROP TABLE history_migration_backup;
ALTER TABLE workbench_entity_mention ADD COLUMN occurrence_key TEXT;
ALTER TABLE workbench_entity_mention ADD COLUMN extractor_version TEXT;
ALTER TABLE workbench_entity_mention ADD COLUMN surface_text TEXT;
ALTER TABLE workbench_entity_mention ADD COLUMN start_offset INTEGER;
ALTER TABLE workbench_entity_mention ADD COLUMN end_offset INTEGER;
ALTER TABLE workbench_entity_mention ADD COLUMN date_json TEXT;
ALTER TABLE workbench_entity_mention ADD COLUMN review_status TEXT NOT NULL DEFAULT 'needs_review';
ALTER TABLE workbench_entity ADD COLUMN extractor_version TEXT;

CREATE TABLE workbench_entity_discovery_seen (
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    occurrence_key TEXT NOT NULL,
    PRIMARY KEY(matter_id, occurrence_key)
);
CREATE TABLE workbench_entity_discovery_unit (
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES workbench_review_run(run_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    unit_ordinal INTEGER NOT NULL,
    unit_digest TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','processed','failed','invalidated')),
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(matter_id,run_id,document_id,unit_ordinal,extractor_version)
);
CREATE TABLE workbench_entity_reconciliation (
    operation_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    undone INTEGER NOT NULL DEFAULT 0 CHECK(undone IN (0,1))
);
