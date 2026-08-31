PRAGMA foreign_keys = ON;

-- Durable, queryable projection of the per-matter source manifest. Source bytes
-- and extracted units remain in managed matter storage; this table is the
-- authoritative inventory for paging, filtering, and operational counts.
CREATE TABLE IF NOT EXISTS workbench_source_catalog (
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    action_token TEXT NOT NULL,
    display_name TEXT NOT NULL,
    display_name_key TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    search_key TEXT NOT NULL,
    media_type TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN ('PDF', 'DOCX', 'TXT', 'AUDIO', 'VIDEO', 'IMAGE', 'EMAIL', 'SPREADSHEET')
    ),
    source_state TEXT NOT NULL,
    tone TEXT NOT NULL CHECK (tone IN ('ready', 'processing', 'attention')),
    state_label TEXT NOT NULL,
    count_label TEXT NOT NULL,
    processing_stage TEXT NOT NULL DEFAULT '',
    completed_units INTEGER NOT NULL DEFAULT 0 CHECK (completed_units >= 0),
    total_units INTEGER NOT NULL DEFAULT 0 CHECK (total_units >= 0),
    page_count INTEGER NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    duration_ms INTEGER NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
    byte_size INTEGER NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
    origin TEXT NOT NULL CHECK (origin IN ('upload', 'registered')),
    retryable INTEGER NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)),
    removable INTEGER NOT NULL DEFAULT 1 CHECK (removable IN (0, 1)),
    has_video INTEGER NOT NULL DEFAULT 0 CHECK (has_video IN (0, 1)),
    cataloged_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (matter_id, document_id),
    UNIQUE (matter_id, action_token)
);

CREATE INDEX IF NOT EXISTS workbench_source_catalog_library_idx
    ON workbench_source_catalog(matter_id, tone, kind, updated_at DESC, document_id);

CREATE INDEX IF NOT EXISTS workbench_source_catalog_name_idx
    ON workbench_source_catalog(matter_id, display_name_key, document_id);

CREATE INDEX IF NOT EXISTS workbench_source_catalog_state_idx
    ON workbench_source_catalog(matter_id, source_state, document_id);
