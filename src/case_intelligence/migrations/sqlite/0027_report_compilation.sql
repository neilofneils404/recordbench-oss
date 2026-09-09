PRAGMA foreign_keys = ON;

-- Durable compilation intent; source material remains in its original records.
CREATE TABLE IF NOT EXISTS workbench_report_compilation_job (
    job_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    request_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('timeline','entities','topic')),
    topic TEXT NOT NULL DEFAULT '',
    selections_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued','running','succeeded','failed','cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    worker_id TEXT,
    lease_token TEXT,
    lease_expires_at REAL,
    cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancellation_requested IN (0,1)),
    input_fingerprint TEXT NOT NULL DEFAULT '',
    report_id TEXT REFERENCES workbench_report(report_id) ON DELETE SET NULL,
    message TEXT NOT NULL DEFAULT 'Queued.',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    finished_at REAL,
    UNIQUE (matter_id, actor_id, request_key)
);
CREATE INDEX IF NOT EXISTS workbench_report_compilation_queue_idx
    ON workbench_report_compilation_job(state, created_at, job_id);
CREATE INDEX IF NOT EXISTS workbench_report_compilation_lease_idx
    ON workbench_report_compilation_job(state, lease_expires_at);
CREATE INDEX IF NOT EXISTS workbench_report_compilation_owner_idx
    ON workbench_report_compilation_job(actor_id, matter_id, state, created_at);
