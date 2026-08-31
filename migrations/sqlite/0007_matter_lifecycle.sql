PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_matter_lifecycle (
    matter_id TEXT PRIMARY KEY REFERENCES workbench_matter(matter_id),
    state TEXT NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'purging', 'purge_failed', 'deleted')),
    purge_id TEXT UNIQUE,
    requested_by TEXT REFERENCES workbench_principal(principal_id),
    requested_at TEXT,
    finished_at TEXT,
    error_code TEXT,
    source_count INTEGER NOT NULL DEFAULT 0 CHECK (source_count >= 0),
    conversation_count INTEGER NOT NULL DEFAULT 0 CHECK (conversation_count >= 0),
    message_count INTEGER NOT NULL DEFAULT 0 CHECK (message_count >= 0),
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS workbench_matter_lifecycle_state_idx
    ON workbench_matter_lifecycle(state, updated_at DESC);

INSERT OR IGNORE INTO workbench_matter_lifecycle(
    matter_id, state, purge_id, requested_by, requested_at, finished_at,
    error_code, source_count, conversation_count, message_count, updated_at
)
SELECT matter_id, 'active', NULL, NULL, NULL, NULL, NULL, 0, 0, 0, updated_at
FROM workbench_matter;

