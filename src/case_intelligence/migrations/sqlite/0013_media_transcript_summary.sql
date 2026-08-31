PRAGMA foreign_keys = ON;

-- A transcript overview is derived, fallible orientation. New imports enqueue
-- one row atomically. The application coordinator idempotently queues any
-- older transcript that lacks a row without placing transcript text in this
-- migration or running a model inside schema application.
CREATE TABLE IF NOT EXISTS workbench_media_summary (
    transcript_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued'
        CHECK (state IN ('queued', 'running', 'ready', 'stale', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    payload_json TEXT NOT NULL DEFAULT '{}',
    basis_digest TEXT NOT NULL DEFAULT ''
        CHECK (basis_digest = '' OR length(basis_digest) = 64),
    covered_segment_count INTEGER NOT NULL DEFAULT 0
        CHECK (covered_segment_count >= 0),
    total_segment_count INTEGER NOT NULL DEFAULT 0
        CHECK (total_segment_count >= 0),
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (matter_id, transcript_id)
        REFERENCES workbench_media_transcript(matter_id, transcript_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS workbench_media_summary_queue_idx
    ON workbench_media_summary(state, created_at, transcript_id);

CREATE INDEX IF NOT EXISTS workbench_media_summary_source_idx
    ON workbench_media_summary(
        matter_id, document_id, source_version_id, updated_at DESC
    );

CREATE TRIGGER IF NOT EXISTS workbench_media_summary_transcript_guard
BEFORE INSERT ON workbench_media_summary
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM workbench_media_transcript transcript
        WHERE transcript.transcript_id = NEW.transcript_id
          AND transcript.matter_id = NEW.matter_id
          AND transcript.document_id = NEW.document_id
          AND transcript.source_version_id = NEW.source_version_id
    ) THEN RAISE(ABORT, 'media summary crossed a transcript boundary') END;
END;
