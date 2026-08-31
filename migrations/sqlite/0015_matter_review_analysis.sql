PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_analysis_run (
    analysis_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    requested_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    state TEXT NOT NULL CHECK (state IN ('running', 'complete', 'failed')),
    source_count INTEGER NOT NULL DEFAULT 0 CHECK (source_count >= 0),
    unit_count INTEGER NOT NULL DEFAULT 0 CHECK (unit_count >= 0),
    entity_count INTEGER NOT NULL DEFAULT 0 CHECK (entity_count >= 0),
    finding_count INTEGER NOT NULL DEFAULT 0 CHECK (finding_count >= 0),
    capped INTEGER NOT NULL DEFAULT 0 CHECK (capped IN (0, 1)),
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS workbench_analysis_run_matter_idx
    ON workbench_analysis_run(matter_id, created_at DESC, analysis_id);

CREATE TABLE IF NOT EXISTS workbench_review_finding (
    finding_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('comparison', 'contradiction')),
    signature TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'suggested'
        CHECK (status IN ('suggested', 'confirmed', 'needs_review', 'dismissed')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, kind, signature),
    UNIQUE (matter_id, finding_id)
);

CREATE INDEX IF NOT EXISTS workbench_review_finding_matter_idx
    ON workbench_review_finding(matter_id, active, kind, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS workbench_review_finding_reference (
    reference_id TEXT PRIMARY KEY,
    finding_id TEXT NOT NULL,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    document_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    location TEXT NOT NULL,
    unit_number INTEGER NOT NULL CHECK (unit_number > 0),
    chunk_id TEXT NOT NULL,
    excerpt_digest TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    support_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (finding_id, ordinal),
    FOREIGN KEY (matter_id, finding_id)
        REFERENCES workbench_review_finding(matter_id, finding_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS workbench_review_finding_reference_source_idx
    ON workbench_review_finding_reference(matter_id, document_id, finding_id);
