PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_notebook_item (
    item_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    item_type TEXT NOT NULL
        CHECK (item_type IN ('fact', 'issue', 'person', 'place', 'date', 'event', 'note')),
    status TEXT NOT NULL DEFAULT 'needs_review'
        CHECK (status IN ('suggested', 'confirmed', 'disputed', 'needs_review', 'dismissed')),
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    date_label TEXT NOT NULL DEFAULT '',
    is_pinned INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1)),
    origin TEXT NOT NULL DEFAULT 'manual'
        CHECK (origin IN ('manual', 'answer', 'citation', 'extraction')),
    source_conversation_id TEXT,
    source_message_id TEXT,
    dedupe_key TEXT,
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, item_id),
    UNIQUE (matter_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS workbench_notebook_item_library_idx
    ON workbench_notebook_item(
        matter_id, status, is_pinned DESC, updated_at DESC, item_id DESC
    );

CREATE INDEX IF NOT EXISTS workbench_notebook_item_type_idx
    ON workbench_notebook_item(
        matter_id, item_type, status, updated_at DESC, item_id DESC
    );

CREATE TABLE IF NOT EXISTS workbench_notebook_reference (
    reference_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
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
    support_token TEXT NOT NULL CHECK (length(support_token) = 40),
    created_at TEXT NOT NULL,
    UNIQUE (item_id, ordinal),
    FOREIGN KEY (matter_id, item_id)
        REFERENCES workbench_notebook_item(matter_id, item_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS workbench_notebook_reference_item_idx
    ON workbench_notebook_reference(matter_id, item_id, ordinal);

CREATE INDEX IF NOT EXISTS workbench_notebook_reference_source_idx
    ON workbench_notebook_reference(
        matter_id, document_id, source_version_id, unit_number
    );

-- The answer scope is a visible, immutable-at-submission snapshot. It records
-- exactly which notebook text the user elected to provide as orientation to a
-- later answer. Notebook text is never treated as source evidence.
CREATE TABLE IF NOT EXISTS workbench_answer_notebook_scope (
    job_id TEXT PRIMARY KEY REFERENCES workbench_answer_job(job_id) ON DELETE CASCADE,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK (mode IN ('confirmed', 'selected')),
    item_count INTEGER NOT NULL CHECK (item_count BETWEEN 1 AND 50),
    created_at TEXT NOT NULL,
    UNIQUE (matter_id, job_id)
);

CREATE TABLE IF NOT EXISTS workbench_answer_notebook_scope_item (
    job_id TEXT NOT NULL,
    matter_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 1 AND 50),
    notebook_item_id TEXT NOT NULL,
    item_type TEXT NOT NULL
        CHECK (item_type IN ('fact', 'issue', 'person', 'place', 'date', 'event', 'note')),
    status TEXT NOT NULL
        CHECK (status IN ('suggested', 'confirmed', 'disputed', 'needs_review', 'dismissed')),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    date_label TEXT NOT NULL,
    content_digest TEXT NOT NULL CHECK (length(content_digest) = 64),
    PRIMARY KEY (job_id, ordinal),
    UNIQUE (job_id, notebook_item_id),
    FOREIGN KEY (matter_id, job_id)
        REFERENCES workbench_answer_notebook_scope(matter_id, job_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS workbench_answer_notebook_scope_matter_idx
    ON workbench_answer_notebook_scope(matter_id, created_at DESC, job_id);

CREATE TRIGGER IF NOT EXISTS workbench_answer_notebook_scope_matter_guard
BEFORE INSERT ON workbench_answer_notebook_scope
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM workbench_answer_job job
        WHERE job.job_id = NEW.job_id AND job.matter_id = NEW.matter_id
    ) THEN RAISE(ABORT, 'answer notebook scope crossed a matter boundary') END;
END;
