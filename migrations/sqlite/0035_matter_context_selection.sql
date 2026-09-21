-- References deliberately survive source-record deletion; never rebind by name.
CREATE TABLE IF NOT EXISTS workbench_context_selection (
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    PRIMARY KEY (matter_id, owner_id)
);
CREATE TABLE IF NOT EXISTS workbench_context_entry (
    matter_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('notebook_item','entity','assertion')),
    object_id TEXT NOT NULL CHECK (length(object_id) BETWEEN 1 AND 80),
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 1 AND 50),
    approval_json TEXT NOT NULL CHECK (length(approval_json) <= 1024),
    selected_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    selected_at TEXT NOT NULL,
    PRIMARY KEY (matter_id, owner_id, kind, object_id),
    UNIQUE (matter_id, owner_id, ordinal),
    FOREIGN KEY (matter_id, owner_id) REFERENCES workbench_context_selection(matter_id, owner_id) ON DELETE CASCADE
);
