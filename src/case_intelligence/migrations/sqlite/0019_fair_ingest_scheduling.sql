PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_job_matter_schedule (
    queue_kind TEXT NOT NULL
        CHECK (queue_kind IN ('ingest', 'media', 'media_summary')),
    matter_id TEXT NOT NULL
        REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    claim_sequence INTEGER NOT NULL CHECK (claim_sequence > 0),
    PRIMARY KEY (queue_kind, matter_id)
) WITHOUT ROWID;
