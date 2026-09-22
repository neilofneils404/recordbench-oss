-- Historical orientation belongs to the existing answer, never the live selection.
CREATE UNIQUE INDEX IF NOT EXISTS answer_context_job_matter ON workbench_answer_job(job_id,matter_id);
CREATE TABLE IF NOT EXISTS workbench_answer_context (
    job_id TEXT PRIMARY KEY REFERENCES workbench_answer_job(job_id) ON DELETE CASCADE,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    snapshot_json TEXT NOT NULL CHECK(length(CAST(snapshot_json AS BLOB)) <= 524288),
    FOREIGN KEY(job_id,matter_id) REFERENCES workbench_answer_job(job_id,matter_id) ON DELETE CASCADE
);
CREATE TRIGGER IF NOT EXISTS answer_context_immutable BEFORE UPDATE ON workbench_answer_context
BEGIN SELECT RAISE(ABORT, 'Submitted context is immutable'); END;
CREATE TABLE IF NOT EXISTS workbench_answer_context_attempt (
    job_id TEXT NOT NULL REFERENCES workbench_answer_context(job_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 16),
    worker_attempt INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('prepared','dispatch_attempted','transport_failed','completed')),
    manifest_json TEXT NOT NULL CHECK(length(CAST(manifest_json AS BLOB)) <= 131072),
    response_json TEXT CHECK(length(CAST(response_json AS BLOB)) <= 8192),
    prepared_at TEXT NOT NULL,
    attempted_at TEXT,
    completed_at TEXT,
    PRIMARY KEY(job_id, ordinal)
);
CREATE TRIGGER IF NOT EXISTS answer_manifest_immutable BEFORE UPDATE OF manifest_json,job_id,ordinal,worker_attempt,prepared_at ON workbench_answer_context_attempt
BEGIN SELECT RAISE(ABORT, 'Prepared input is immutable'); END;

CREATE TRIGGER IF NOT EXISTS answer_response_immutable BEFORE UPDATE OF response_json ON workbench_answer_context_attempt
WHEN OLD.response_json IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'Dispatch outcome is immutable'); END;
