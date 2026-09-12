PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_entity (
    entity_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('person', 'place', 'thing')),
    display_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('suggested', 'needs_review', 'confirmed', 'disputed', 'dismissed')),
    aliases_json TEXT NOT NULL DEFAULT '[]',
    origin TEXT NOT NULL CHECK (origin IN ('manual', 'notebook')),
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
CREATE INDEX IF NOT EXISTS workbench_entity_matter_idx
    ON workbench_entity(matter_id, display_name, entity_id);

CREATE TABLE IF NOT EXISTS workbench_entity_mention (
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
    origin TEXT NOT NULL CHECK (origin IN ('manual', 'notebook')),
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    UNIQUE (entity_id, support_token),
    FOREIGN KEY (matter_id, entity_id) REFERENCES workbench_entity(matter_id, entity_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS workbench_entity_mention_source_idx
    ON workbench_entity_mention(matter_id, document_id, source_version_id);

CREATE TABLE IF NOT EXISTS workbench_entity_history (
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
