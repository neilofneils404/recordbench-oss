PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_ingest_plan (
    plan_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    source_location_id TEXT NOT NULL,
    source_label TEXT NOT NULL,
    relative_folder TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('review', 'confirmed', 'cancelled')),
    supported_count INTEGER NOT NULL CHECK (supported_count >= 0),
    unsupported_count INTEGER NOT NULL CHECK (unsupported_count >= 0),
    total_bytes INTEGER NOT NULL CHECK (total_bytes >= 0),
    created_at TEXT NOT NULL,
    confirmed_at TEXT
);

CREATE INDEX IF NOT EXISTS workbench_ingest_plan_matter_idx
    ON workbench_ingest_plan(matter_id, created_at DESC);

CREATE TABLE IF NOT EXISTS workbench_ingest_plan_item (
    plan_id TEXT NOT NULL REFERENCES workbench_ingest_plan(plan_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    relative_path TEXT NOT NULL,
    display_name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size > 0),
    stable_device INTEGER NOT NULL CHECK (stable_device >= 0),
    stable_inode INTEGER NOT NULL CHECK (stable_inode >= 0),
    stable_mtime_ns INTEGER NOT NULL CHECK (stable_mtime_ns >= 0),
    document_id TEXT,
    PRIMARY KEY (plan_id, ordinal),
    UNIQUE (plan_id, relative_path)
);

CREATE TABLE IF NOT EXISTS workbench_ingest_job (
    job_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    plan_id TEXT REFERENCES workbench_ingest_plan(plan_id) ON DELETE CASCADE,
    source_location_id TEXT,
    relative_path TEXT,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    stage TEXT NOT NULL,
    completed_units INTEGER NOT NULL DEFAULT 0 CHECK (completed_units >= 0),
    total_units INTEGER NOT NULL DEFAULT 0 CHECK (total_units >= 0),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    worker_id TEXT,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, document_id)
);

CREATE INDEX IF NOT EXISTS workbench_ingest_job_queue_idx
    ON workbench_ingest_job(state, created_at, job_id);

CREATE INDEX IF NOT EXISTS workbench_ingest_job_matter_idx
    ON workbench_ingest_job(matter_id, updated_at DESC);
