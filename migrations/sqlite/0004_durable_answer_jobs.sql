PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_answer_job (
    job_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL REFERENCES workbench_conversation(conversation_id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    question TEXT NOT NULL,
    question_message_id TEXT NOT NULL UNIQUE REFERENCES workbench_message(message_id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    stage TEXT NOT NULL CHECK (stage IN ('queued', 'retrieving', 'reranking', 'generating', 'verifying', 'complete', 'failed', 'cancelling', 'cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    worker_id TEXT,
    cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancellation_requested IN (0, 1)),
    result_message_id TEXT UNIQUE REFERENCES workbench_message(message_id) ON DELETE SET NULL,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    last_claimed_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (actor_id, matter_id, conversation_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS workbench_answer_job_queue_idx
    ON workbench_answer_job(state, created_at, job_id);

CREATE INDEX IF NOT EXISTS workbench_answer_job_scope_idx
    ON workbench_answer_job(actor_id, matter_id, conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS workbench_answer_job_lane_idx
    ON workbench_answer_job(actor_id, matter_id, last_claimed_at);

CREATE TABLE IF NOT EXISTS workbench_answer_event (
    job_id TEXT NOT NULL REFERENCES workbench_answer_job(job_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    stage TEXT NOT NULL CHECK (stage IN ('queued', 'retrieving', 'reranking', 'generating', 'verifying', 'complete', 'failed', 'cancelling', 'cancelled')),
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (job_id, ordinal)
);

CREATE INDEX IF NOT EXISTS workbench_answer_event_job_idx
    ON workbench_answer_event(job_id, ordinal);
