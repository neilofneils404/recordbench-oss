PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_report (
    report_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'final')),
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    updated_at TEXT NOT NULL,
    UNIQUE (matter_id, report_id)
);

CREATE INDEX IF NOT EXISTS workbench_report_matter_idx
    ON workbench_report(matter_id, updated_at DESC, report_id);

CREATE TABLE IF NOT EXISTS workbench_report_section (
    section_id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    heading TEXT NOT NULL,
    body TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (
        origin IN ('manual', 'notebook', 'answer', 'finding', 'media_clip')
    ),
    origin_id TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    updated_at TEXT NOT NULL,
    UNIQUE (report_id, ordinal),
    UNIQUE (matter_id, section_id),
    FOREIGN KEY (matter_id, report_id)
        REFERENCES workbench_report(matter_id, report_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS workbench_report_section_report_idx
    ON workbench_report_section(matter_id, report_id, ordinal);

CREATE TABLE IF NOT EXISTS workbench_report_citation (
    citation_id TEXT PRIMARY KEY,
    section_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    kind TEXT NOT NULL CHECK (kind IN ('source', 'transcript', 'media_clip')),
    document_id TEXT NOT NULL DEFAULT '',
    source_version_id TEXT NOT NULL DEFAULT '',
    source_name TEXT NOT NULL,
    location TEXT NOT NULL,
    support_token TEXT NOT NULL DEFAULT '',
    excerpt TEXT NOT NULL DEFAULT '',
    media_clip_id TEXT NOT NULL DEFAULT '',
    start_ms INTEGER NOT NULL DEFAULT 0 CHECK (start_ms >= 0),
    end_ms INTEGER NOT NULL DEFAULT 0 CHECK (end_ms >= 0),
    created_at TEXT NOT NULL,
    UNIQUE (section_id, ordinal),
    FOREIGN KEY (matter_id, section_id)
        REFERENCES workbench_report_section(matter_id, section_id)
        ON DELETE CASCADE,
    FOREIGN KEY (matter_id, report_id)
        REFERENCES workbench_report(matter_id, report_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS workbench_report_citation_source_idx
    ON workbench_report_citation(matter_id, document_id, report_id, section_id);
