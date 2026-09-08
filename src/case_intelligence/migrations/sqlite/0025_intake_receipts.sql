PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_intake_receipt (
    receipt_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    selection_key TEXT NOT NULL,
    selection_fingerprint TEXT NOT NULL,
    collection_name TEXT NOT NULL,
    selected_count INTEGER NOT NULL CHECK (selected_count BETWEEN 1 AND 10000),
    eligible_indexes_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('recording', 'ready')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, actor_id, selection_key),
    UNIQUE (receipt_id, matter_id)
);
CREATE INDEX IF NOT EXISTS workbench_intake_receipt_matter_idx
    ON workbench_intake_receipt(matter_id, created_at DESC, receipt_id);

CREATE TABLE IF NOT EXISTS workbench_intake_item (
    receipt_id TEXT NOT NULL,
    matter_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 9999),
    descriptor_digest TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    display_name TEXT NOT NULL,
    expected_size INTEGER,
    expected_type TEXT NOT NULL,
    supplied_type TEXT NOT NULL,
    preflight_state TEXT NOT NULL CHECK (preflight_state IN ('valid','needs_attention','unsupported','duplicate_candidate','over_limit','failed')),
    selected_for_upload INTEGER NOT NULL CHECK (selected_for_upload IN (0,1)),
    reason TEXT NOT NULL,
    PRIMARY KEY (receipt_id, ordinal),
    UNIQUE (receipt_id, ordinal, matter_id),
    FOREIGN KEY (receipt_id, matter_id) REFERENCES workbench_intake_receipt(receipt_id, matter_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS workbench_intake_item_matter_idx
    ON workbench_intake_item(matter_id, receipt_id, ordinal);

CREATE TABLE IF NOT EXISTS workbench_intake_transfer (
    receipt_id TEXT NOT NULL,
    matter_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    upload_item_id TEXT NOT NULL UNIQUE,
    source_version_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (receipt_id, ordinal),
    FOREIGN KEY (receipt_id, ordinal, matter_id) REFERENCES workbench_intake_item(receipt_id, ordinal, matter_id) ON DELETE CASCADE,
    FOREIGN KEY (upload_item_id) REFERENCES workbench_upload_item(upload_item_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS workbench_intake_transfer_matter_idx
    ON workbench_intake_transfer(matter_id, receipt_id);
