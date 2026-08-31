PRAGMA foreign_keys = ON;

-- The workbench owns durable media state. The transcription service receives a
-- transient copy and is referenced only by its opaque job identifier.
CREATE TABLE IF NOT EXISTS workbench_media_job (
    media_job_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    requested_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    state TEXT NOT NULL DEFAULT 'queued'
        CHECK (state IN ('queued', 'running', 'succeeded', 'degraded', 'failed', 'cancelled')),
    stage TEXT NOT NULL DEFAULT 'Queued',
    progress REAL NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 1),
    external_job_id TEXT,
    source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
    byte_size INTEGER NOT NULL CHECK (byte_size > 0),
    media_type TEXT NOT NULL,
    duration_ms INTEGER NOT NULL CHECK (duration_ms > 0),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    worker_id TEXT,
    degraded INTEGER NOT NULL DEFAULT 0 CHECK (degraded IN (0, 1)),
    message TEXT NOT NULL DEFAULT '',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    quality_json TEXT NOT NULL DEFAULT '{}',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, document_id, source_version_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS workbench_media_job_external_idx
    ON workbench_media_job(external_job_id) WHERE external_job_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS workbench_media_job_queue_idx
    ON workbench_media_job(state, created_at, media_job_id);

CREATE INDEX IF NOT EXISTS workbench_media_job_matter_idx
    ON workbench_media_job(matter_id, updated_at DESC, media_job_id);

CREATE TABLE IF NOT EXISTS workbench_media_transcript (
    transcript_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    media_job_id TEXT NOT NULL REFERENCES workbench_media_job(media_job_id) ON DELETE CASCADE,
    review_state TEXT NOT NULL DEFAULT 'machine_draft'
        CHECK (review_state IN ('machine_draft', 'human_reviewed')),
    duration_ms INTEGER NOT NULL CHECK (duration_ms > 0),
    segment_count INTEGER NOT NULL CHECK (segment_count >= 0),
    transcript_digest TEXT NOT NULL CHECK (length(transcript_digest) = 64),
    warnings_json TEXT NOT NULL DEFAULT '[]',
    quality_json TEXT NOT NULL DEFAULT '{}',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    imported_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    imported_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, document_id, source_version_id),
    UNIQUE (matter_id, transcript_id)
);

CREATE INDEX IF NOT EXISTS workbench_media_transcript_matter_idx
    ON workbench_media_transcript(matter_id, updated_at DESC, transcript_id);

CREATE TABLE IF NOT EXISTS workbench_transcript_segment (
    segment_id TEXT PRIMARY KEY,
    transcript_id TEXT NOT NULL REFERENCES workbench_media_transcript(transcript_id) ON DELETE CASCADE,
    matter_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    external_segment_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
    speaker_cluster TEXT NOT NULL,
    model_text TEXT NOT NULL,
    translated_text TEXT,
    confidence REAL,
    low_confidence INTEGER NOT NULL DEFAULT 0 CHECK (low_confidence IN (0, 1)),
    overlap INTEGER NOT NULL DEFAULT 0 CHECK (overlap IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (transcript_id, ordinal),
    UNIQUE (transcript_id, external_segment_id),
    UNIQUE (matter_id, segment_id),
    FOREIGN KEY (matter_id, transcript_id)
        REFERENCES workbench_media_transcript(matter_id, transcript_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS workbench_transcript_segment_time_idx
    ON workbench_transcript_segment(transcript_id, start_ms, end_ms, ordinal);

-- Machine text above is immutable. Every correction is an attributed append-only
-- revision and uses expected_revision optimistic concurrency in application code.
CREATE TABLE IF NOT EXISTS workbench_transcript_segment_revision (
    revision_id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL,
    matter_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    text TEXT NOT NULL,
    edited_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    edited_at TEXT NOT NULL,
    UNIQUE (segment_id, revision),
    FOREIGN KEY (matter_id, segment_id)
        REFERENCES workbench_transcript_segment(matter_id, segment_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workbench_speaker_mapping_revision (
    mapping_revision_id TEXT PRIMARY KEY,
    transcript_id TEXT NOT NULL,
    matter_id TEXT NOT NULL,
    speaker_cluster TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    display_name TEXT NOT NULL,
    identity_state TEXT NOT NULL
        CHECK (identity_state IN ('cluster', 'confirmed')),
    edited_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    edited_at TEXT NOT NULL,
    UNIQUE (transcript_id, speaker_cluster, revision),
    FOREIGN KEY (matter_id, transcript_id)
        REFERENCES workbench_media_transcript(matter_id, transcript_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS workbench_speaker_mapping_current_idx
    ON workbench_speaker_mapping_revision(
        transcript_id, speaker_cluster, revision DESC
    );

-- A clip is a work-product definition. Source bytes are materialized with
-- FFmpeg only for an authenticated download and are not retained afterward.
CREATE TABLE IF NOT EXISTS workbench_media_clip (
    clip_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    title TEXT NOT NULL,
    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    UNIQUE (matter_id, clip_id)
);

CREATE INDEX IF NOT EXISTS workbench_media_clip_source_idx
    ON workbench_media_clip(
        matter_id, document_id, source_version_id, start_ms, clip_id
    );

CREATE TRIGGER IF NOT EXISTS workbench_media_job_matter_guard
BEFORE INSERT ON workbench_media_job
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM workbench_matter_lifecycle lifecycle
        WHERE lifecycle.matter_id = NEW.matter_id AND lifecycle.state = 'active'
    ) THEN RAISE(ABORT, 'media job requires an active matter') END;
END;

CREATE TRIGGER IF NOT EXISTS workbench_media_transcript_job_guard
BEFORE INSERT ON workbench_media_transcript
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM workbench_media_job job
        WHERE job.media_job_id = NEW.media_job_id
          AND job.matter_id = NEW.matter_id
          AND job.document_id = NEW.document_id
          AND job.source_version_id = NEW.source_version_id
    ) THEN RAISE(ABORT, 'transcript crossed a media job boundary') END;
END;

CREATE TRIGGER IF NOT EXISTS workbench_media_clip_source_guard
BEFORE INSERT ON workbench_media_clip
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM workbench_media_transcript transcript
        WHERE transcript.matter_id = NEW.matter_id
          AND transcript.document_id = NEW.document_id
          AND transcript.source_version_id = NEW.source_version_id
    ) THEN RAISE(ABORT, 'clip crossed a transcript boundary') END;
END;
