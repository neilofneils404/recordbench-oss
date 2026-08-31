PRAGMA foreign_keys = ON;

-- Matter readiness joins unfinished upload items to the current source
-- catalog without materializing either collection in application memory.
CREATE INDEX IF NOT EXISTS workbench_upload_item_matter_document_idx
    ON workbench_upload_item(matter_id, document_id, state);

CREATE INDEX IF NOT EXISTS workbench_upload_session_matter_state_idx
    ON workbench_upload_session(matter_id, state, upload_session_id);

-- A draft's first question may be retried after a lost HTTP response. This
-- lookup resolves the already-created conversation and job by actor/matter
-- request key while preserving the older per-conversation uniqueness rule.
CREATE UNIQUE INDEX IF NOT EXISTS workbench_answer_job_draft_request_idx
    ON workbench_answer_job(actor_id, matter_id, idempotency_key);

CREATE INDEX IF NOT EXISTS workbench_media_summary_matter_state_idx
    ON workbench_media_summary(matter_id, state, updated_at);
