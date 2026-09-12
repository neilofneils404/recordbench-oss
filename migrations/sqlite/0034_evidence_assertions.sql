CREATE TABLE IF NOT EXISTS workbench_assertion (
    assertion_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    record_type TEXT NOT NULL CHECK (record_type IN ('assertion', 'event')),
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    raw_date TEXT NOT NULL DEFAULT '',
    date_uncertainty TEXT NOT NULL DEFAULT '',
    sort_date TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('needs_review', 'confirmed', 'disputed', 'dismissed')),
    origin TEXT NOT NULL DEFAULT 'manual' CHECK (origin = 'manual'),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, assertion_id)
);
CREATE INDEX IF NOT EXISTS workbench_assertion_chronology_idx
    ON workbench_assertion(matter_id, sort_date, created_at, assertion_id);

CREATE TABLE IF NOT EXISTS workbench_assertion_role (
    role_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL,
    assertion_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('subject', 'participant', 'speaker', 'witness', 'location', 'object', 'organization')),
    -- Deliberately no entity foreign key: deletion or reconciliation must not
    -- erase or silently rebind the identity the reviewer explicitly selected.
    entity_id TEXT NOT NULL,
    entity_revision INTEGER NOT NULL CHECK (entity_revision > 0),
    display_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    UNIQUE (assertion_id, entity_id, role),
    FOREIGN KEY (matter_id, assertion_id) REFERENCES workbench_assertion(matter_id, assertion_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS workbench_assertion_role_entity_idx
    ON workbench_assertion_role(matter_id, entity_id, assertion_id);

CREATE TABLE IF NOT EXISTS workbench_assertion_account (
    account_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL,
    assertion_id TEXT NOT NULL,
    stance TEXT NOT NULL CHECK (stance IN ('supporting', 'competing')),
    attributed_to TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    location TEXT NOT NULL,
    unit_number INTEGER NOT NULL CHECK (unit_number > 0),
    chunk_id TEXT NOT NULL,
    excerpt_digest TEXT NOT NULL CHECK (length(excerpt_digest) = 64),
    excerpt TEXT NOT NULL,
    support_token TEXT NOT NULL CHECK (length(support_token) = 40),
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    UNIQUE (assertion_id, support_token, attributed_to),
    FOREIGN KEY (matter_id, assertion_id) REFERENCES workbench_assertion(matter_id, assertion_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS workbench_assertion_account_source_idx
    ON workbench_assertion_account(matter_id, document_id, source_version_id);

CREATE TABLE IF NOT EXISTS workbench_assertion_history (
    assertion_id TEXT NOT NULL,
    matter_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    action TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    actor_id TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (assertion_id, revision),
    FOREIGN KEY (matter_id, assertion_id) REFERENCES workbench_assertion(matter_id, assertion_id) ON DELETE CASCADE
);
