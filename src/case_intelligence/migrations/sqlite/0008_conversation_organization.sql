PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_conversation_organization (
    conversation_id TEXT PRIMARY KEY
        REFERENCES workbench_conversation(conversation_id) ON DELETE CASCADE,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'archived')),
    is_pinned INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1)),
    archived_at TEXT,
    archived_by TEXT REFERENCES workbench_principal(principal_id),
    updated_by TEXT REFERENCES workbench_principal(principal_id),
    updated_at TEXT NOT NULL,
    CHECK (
        (state = 'active' AND archived_at IS NULL AND archived_by IS NULL)
        OR
        (state = 'archived' AND archived_at IS NOT NULL AND archived_by IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS workbench_conversation_organization_scope_idx
    ON workbench_conversation_organization(
        matter_id, state, is_pinned DESC, updated_at DESC, conversation_id DESC
    );

INSERT OR IGNORE INTO workbench_conversation_organization(
    conversation_id, matter_id, state, is_pinned,
    archived_at, archived_by, updated_by, updated_at
)
SELECT conversation_id, matter_id, 'active', 0, NULL, NULL, NULL, updated_at
FROM workbench_conversation;
