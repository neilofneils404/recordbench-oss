PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_source_collection (
    collection_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('upload', 'registered', 'migrated')),
    created_by TEXT REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, name_key),
    UNIQUE (matter_id, collection_id)
);

CREATE INDEX IF NOT EXISTS workbench_source_collection_matter_idx
    ON workbench_source_collection(matter_id, updated_at DESC, collection_id);

CREATE TABLE IF NOT EXISTS workbench_source_organization (
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    collection_id TEXT REFERENCES workbench_source_collection(collection_id) ON DELETE SET NULL,
    relative_path TEXT NOT NULL,
    review_state TEXT NOT NULL DEFAULT 'unreviewed'
        CHECK (review_state IN ('unreviewed', 'reviewed', 'flagged')),
    added_by TEXT REFERENCES workbench_principal(principal_id),
    added_at TEXT NOT NULL,
    updated_by TEXT REFERENCES workbench_principal(principal_id),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (matter_id, document_id),
    FOREIGN KEY (matter_id, collection_id)
        REFERENCES workbench_source_collection(matter_id, collection_id)
);

CREATE INDEX IF NOT EXISTS workbench_source_organization_library_idx
    ON workbench_source_organization(
        matter_id, collection_id, review_state, updated_at DESC, document_id
    );

CREATE TABLE IF NOT EXISTS workbench_source_set (
    source_set_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, name_key),
    UNIQUE (matter_id, source_set_id)
);

CREATE INDEX IF NOT EXISTS workbench_source_set_matter_idx
    ON workbench_source_set(matter_id, updated_at DESC, source_set_id);

CREATE TABLE IF NOT EXISTS workbench_source_set_item (
    source_set_id TEXT NOT NULL,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    added_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    added_at TEXT NOT NULL,
    PRIMARY KEY (source_set_id, document_id),
    FOREIGN KEY (matter_id, source_set_id)
        REFERENCES workbench_source_set(matter_id, source_set_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS workbench_source_set_item_document_idx
    ON workbench_source_set_item(matter_id, document_id, source_set_id);

CREATE TABLE IF NOT EXISTS workbench_upload_session (
    upload_session_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    collection_id TEXT NOT NULL,
    actor_id TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    state TEXT NOT NULL CHECK (state IN ('open', 'complete', 'partial', 'cancelled')),
    item_count INTEGER NOT NULL CHECK (item_count > 0),
    total_bytes INTEGER NOT NULL CHECK (total_bytes > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, upload_session_id),
    FOREIGN KEY (matter_id, collection_id)
        REFERENCES workbench_source_collection(matter_id, collection_id)
);

CREATE INDEX IF NOT EXISTS workbench_upload_session_actor_idx
    ON workbench_upload_session(matter_id, actor_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS workbench_upload_item (
    upload_item_id TEXT PRIMARY KEY,
    upload_session_id TEXT NOT NULL,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    display_name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    media_type TEXT NOT NULL,
    expected_size INTEGER NOT NULL CHECK (expected_size > 0),
    received_size INTEGER NOT NULL DEFAULT 0
        CHECK (received_size >= 0 AND received_size <= expected_size),
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'uploading', 'uploaded', 'queued', 'failed', 'cancelled')),
    document_id TEXT,
    message TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE (upload_session_id, ordinal),
    UNIQUE (upload_session_id, relative_path),
    FOREIGN KEY (matter_id, upload_session_id)
        REFERENCES workbench_upload_session(matter_id, upload_session_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS workbench_upload_item_session_idx
    ON workbench_upload_item(upload_session_id, state, ordinal);

CREATE TABLE IF NOT EXISTS workbench_answer_source_scope (
    job_id TEXT PRIMARY KEY REFERENCES workbench_answer_job(job_id) ON DELETE CASCADE,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    source_set_id TEXT NOT NULL,
    FOREIGN KEY (matter_id, source_set_id)
        REFERENCES workbench_source_set(matter_id, source_set_id)
);

CREATE INDEX IF NOT EXISTS workbench_answer_source_scope_set_idx
    ON workbench_answer_source_scope(matter_id, source_set_id, job_id);
