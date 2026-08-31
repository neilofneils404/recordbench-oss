PRAGMA foreign_keys = ON;

-- Retention is deliberately opt-in for pre-A22 matters.  New matters receive
-- an explicit schedule through the application create flow; this migration
-- does not silently assign dates to existing work.
CREATE TABLE IF NOT EXISTS workbench_matter_retention (
    matter_id TEXT PRIMARY KEY REFERENCES workbench_matter(matter_id),
    expires_at TEXT NOT NULL,
    purge_after TEXT NOT NULL,
    scheduled_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (purge_after > expires_at)
);

CREATE INDEX IF NOT EXISTS workbench_matter_retention_due_idx
    ON workbench_matter_retention(purge_after, expires_at, matter_id);

-- Appearance is a user preference, not matter content.  The broader allowed
-- set keeps future authored themes additive while the current UI exposes only
-- the reviewed Light and Dusk themes.
CREATE TABLE IF NOT EXISTS workbench_principal_preference (
    principal_id TEXT PRIMARY KEY REFERENCES workbench_principal(principal_id)
        ON DELETE CASCADE,
    theme TEXT NOT NULL DEFAULT 'light'
        CHECK (theme IN ('light', 'dusk', 'cyberpunk', 'retro')),
    updated_at TEXT NOT NULL
);
