PRAGMA foreign_keys = ON;

-- Durable multi-pass research. The result payload contains only derived work
-- product and source-bound locators; source bytes remain in managed storage.
CREATE TABLE IF NOT EXISTS workbench_research_job (
    job_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    idempotency_key TEXT NOT NULL,
    question TEXT NOT NULL,
    title TEXT NOT NULL,
    source_set_id TEXT,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    stage TEXT NOT NULL CHECK (stage IN ('queued', 'planning', 'searching', 'synthesizing', 'verifying', 'complete', 'failed', 'cancelling', 'cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    worker_id TEXT,
    cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancellation_requested IN (0, 1)),
    plan_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    total_steps INTEGER NOT NULL DEFAULT 0 CHECK (total_steps >= 0),
    completed_steps INTEGER NOT NULL DEFAULT 0 CHECK (completed_steps >= 0),
    candidate_count INTEGER NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
    evidence_count INTEGER NOT NULL DEFAULT 0 CHECK (evidence_count >= 0),
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    last_claimed_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (actor_id, matter_id, idempotency_key),
    FOREIGN KEY (matter_id, source_set_id)
        REFERENCES workbench_source_set(matter_id, source_set_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS workbench_research_job_queue_idx
    ON workbench_research_job(state, created_at, job_id);
CREATE INDEX IF NOT EXISTS workbench_research_job_scope_idx
    ON workbench_research_job(matter_id, actor_id, created_at DESC, job_id);
CREATE INDEX IF NOT EXISTS workbench_research_job_lane_idx
    ON workbench_research_job(actor_id, matter_id, last_claimed_at);

CREATE TABLE IF NOT EXISTS workbench_research_event (
    job_id TEXT NOT NULL REFERENCES workbench_research_job(job_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    stage TEXT NOT NULL CHECK (stage IN ('queued', 'planning', 'searching', 'synthesizing', 'verifying', 'complete', 'failed', 'cancelling', 'cancelled')),
    completed_steps INTEGER NOT NULL DEFAULT 0 CHECK (completed_steps >= 0),
    total_steps INTEGER NOT NULL DEFAULT 0 CHECK (total_steps >= 0),
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (job_id, ordinal)
);

-- Criteria are editable only by creating a new immutable version. A review
-- run binds to one version and snapshots every eligible source into decisions.
CREATE TABLE IF NOT EXISTS workbench_review_criterion (
    criterion_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, criterion_id)
);

CREATE INDEX IF NOT EXISTS workbench_review_criterion_matter_idx
    ON workbench_review_criterion(matter_id, updated_at DESC, criterion_id);

CREATE TABLE IF NOT EXISTS workbench_review_criterion_version (
    criterion_version_id TEXT PRIMARY KEY,
    criterion_id TEXT NOT NULL,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    instructions TEXT NOT NULL,
    include_guidance TEXT NOT NULL DEFAULT '',
    exclude_guidance TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    UNIQUE (matter_id, criterion_id, version_number),
    UNIQUE (matter_id, criterion_version_id),
    FOREIGN KEY (matter_id, criterion_id)
        REFERENCES workbench_review_criterion(matter_id, criterion_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS workbench_review_criterion_version_idx
    ON workbench_review_criterion_version(matter_id, criterion_id, version_number DESC);

CREATE TABLE IF NOT EXISTS workbench_review_run (
    run_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    criterion_id TEXT NOT NULL,
    criterion_version_id TEXT NOT NULL,
    source_set_id TEXT,
    run_kind TEXT NOT NULL CHECK (run_kind IN ('sample', 'full')),
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    stage TEXT NOT NULL CHECK (stage IN ('queued', 'snapshotting', 'reviewing', 'validating', 'complete', 'failed', 'cancelling', 'cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    worker_id TEXT,
    cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancellation_requested IN (0, 1)),
    snapshot_count INTEGER NOT NULL DEFAULT 0 CHECK (snapshot_count >= 0),
    reviewed_count INTEGER NOT NULL DEFAULT 0 CHECK (reviewed_count >= 0),
    included_count INTEGER NOT NULL DEFAULT 0 CHECK (included_count >= 0),
    excluded_count INTEGER NOT NULL DEFAULT 0 CHECK (excluded_count >= 0),
    attention_count INTEGER NOT NULL DEFAULT 0 CHECK (attention_count >= 0),
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    last_claimed_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (matter_id, criterion_id)
        REFERENCES workbench_review_criterion(matter_id, criterion_id),
    FOREIGN KEY (matter_id, criterion_version_id)
        REFERENCES workbench_review_criterion_version(matter_id, criterion_version_id),
    FOREIGN KEY (matter_id, source_set_id)
        REFERENCES workbench_source_set(matter_id, source_set_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS workbench_review_run_queue_idx
    ON workbench_review_run(state, created_at, run_id);
CREATE INDEX IF NOT EXISTS workbench_review_run_scope_idx
    ON workbench_review_run(matter_id, created_at DESC, run_id);
CREATE INDEX IF NOT EXISTS workbench_review_run_lane_idx
    ON workbench_review_run(actor_id, matter_id, last_claimed_at);

CREATE TABLE IF NOT EXISTS workbench_review_decision (
    run_id TEXT NOT NULL REFERENCES workbench_review_run(run_id) ON DELETE CASCADE,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    document_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    action_token TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    machine_decision TEXT NOT NULL DEFAULT 'pending' CHECK (machine_decision IN ('pending', 'included', 'excluded', 'needs_attention')),
    rationale TEXT NOT NULL DEFAULT '',
    citations_json TEXT NOT NULL DEFAULT '[]',
    error_message TEXT NOT NULL DEFAULT '',
    validation_sample INTEGER NOT NULL DEFAULT 0 CHECK (validation_sample IN (0, 1)),
    human_decision TEXT NOT NULL DEFAULT '' CHECK (human_decision IN ('', 'agree', 'include', 'exclude', 'uncertain')),
    human_note TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT REFERENCES workbench_principal(principal_id),
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, document_id),
    UNIQUE (run_id, ordinal)
);

CREATE INDEX IF NOT EXISTS workbench_review_decision_page_idx
    ON workbench_review_decision(run_id, machine_decision, ordinal);
CREATE INDEX IF NOT EXISTS workbench_review_decision_validation_idx
    ON workbench_review_decision(run_id, validation_sample, human_decision, ordinal);

CREATE TABLE IF NOT EXISTS workbench_review_event (
    run_id TEXT NOT NULL REFERENCES workbench_review_run(run_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    stage TEXT NOT NULL CHECK (stage IN ('queued', 'snapshotting', 'reviewing', 'validating', 'complete', 'failed', 'cancelling', 'cancelled')),
    reviewed_count INTEGER NOT NULL DEFAULT 0 CHECK (reviewed_count >= 0),
    snapshot_count INTEGER NOT NULL DEFAULT 0 CHECK (snapshot_count >= 0),
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, ordinal)
);
