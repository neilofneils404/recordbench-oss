-- Per-principal, matter-bound resume state for the Review Cockpit.
-- Stores only safe object identifiers, kind, numeric locator, and timestamps.
CREATE TABLE IF NOT EXISTS workbench_matter_activity (
    activity_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    activity_kind TEXT NOT NULL
        CHECK (activity_kind IN ('source','conversation','notebook','analysis','report')),
    object_id TEXT NOT NULL,
    locator INTEGER NOT NULL DEFAULT 0
        CHECK (locator >= 0 AND locator <= 43200000),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, principal_id, activity_kind, object_id),
    FOREIGN KEY (matter_id)
        REFERENCES workbench_matter(matter_id)
        ON DELETE CASCADE,
    FOREIGN KEY (principal_id)
        REFERENCES workbench_principal(principal_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS workbench_matter_activity_recent_idx
    ON workbench_matter_activity(
        matter_id, principal_id, updated_at DESC, activity_id DESC
    );

CREATE INDEX IF NOT EXISTS workbench_source_catalog_sequence_idx
    ON workbench_source_catalog(matter_id, cataloged_at, document_id);

