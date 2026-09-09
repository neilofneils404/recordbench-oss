PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS workbench_text_review (
    run_id TEXT PRIMARY KEY REFERENCES workbench_review_run(run_id) ON DELETE CASCADE,
    policy_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workbench_text_review_source (
    run_id TEXT NOT NULL REFERENCES workbench_text_review(run_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    source_basis_digest TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_state TEXT NOT NULL,
    extraction_note TEXT NOT NULL,
    reported_pages INTEGER NOT NULL DEFAULT 0,
    inventory_sealed INTEGER NOT NULL DEFAULT 0 CHECK(inventory_sealed IN (0,1)),
    unit_count INTEGER NOT NULL DEFAULT 0,
    text_chars INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    empty_units INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK(state IN ('pending','inventoried','unavailable','invalidated')),
    PRIMARY KEY(run_id,document_id)
);
CREATE TABLE IF NOT EXISTS workbench_text_review_unit (
    run_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    unit_ordinal INTEGER NOT NULL CHECK(unit_ordinal>0),
    unit_number INTEGER NOT NULL,
    location TEXT NOT NULL,
    unit_digest TEXT NOT NULL,
    text_chars INTEGER NOT NULL CHECK(text_chars>=0),
    chunk_count INTEGER NOT NULL CHECK(chunk_count>=0),
    citation_json TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL CHECK(state IN ('pending','processed','failed','empty','invalidated')),
    PRIMARY KEY(run_id,document_id,unit_ordinal),
    FOREIGN KEY(run_id,document_id) REFERENCES workbench_text_review_source(run_id,document_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS workbench_text_review_chunk (
    run_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    unit_ordinal INTEGER NOT NULL,
    chunk_ordinal INTEGER NOT NULL CHECK(chunk_ordinal>0),
    cursor INTEGER NOT NULL CHECK(cursor>0),
    coverage_start INTEGER NOT NULL CHECK(coverage_start>=0),
    coverage_end INTEGER NOT NULL CHECK(coverage_end>coverage_start),
    packet_start INTEGER NOT NULL CHECK(packet_start>=0 AND packet_start<=coverage_start),
    packet_end INTEGER NOT NULL CHECK(packet_end>=coverage_end),
    state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','processed','failed','invalidated')),
    decision TEXT NOT NULL DEFAULT '' CHECK(decision IN ('','include','exclude')),
    rationale TEXT NOT NULL DEFAULT '',
    finding_key TEXT NOT NULL DEFAULT '',
    attempt INTEGER NOT NULL DEFAULT 0,
    UNIQUE(run_id,document_id,unit_ordinal,chunk_ordinal),
    UNIQUE(run_id,cursor),
    FOREIGN KEY(run_id,document_id,unit_ordinal) REFERENCES workbench_text_review_unit(run_id,document_id,unit_ordinal) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS workbench_text_review_chunk_run_idx ON workbench_text_review_chunk(run_id,state);
