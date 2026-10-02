-- Automatic deterministic discovery runs per current source version, without a
-- criterion review run or a model. Suggestions stay "suggested" until a person
-- decides. Its inactive system principal is created on first use, not here, so
-- a fresh store still starts with no principals.
CREATE TABLE IF NOT EXISTS workbench_entity_auto_discovery_unit (
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    source_version_id TEXT NOT NULL,
    -- Derived text can change within one source version (OCR or transcript
    -- retry); coverage belongs to the exact extracted basis it read.
    content_basis_digest TEXT NOT NULL DEFAULT '',
    -- Ordinal 0 seals the unit inventory of one source version (digest of the count).
    unit_ordinal INTEGER NOT NULL CHECK (unit_ordinal >= 0),
    unit_digest TEXT NOT NULL CHECK (length(unit_digest) = 64),
    extractor_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'processed', 'failed', 'invalidated')),
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (matter_id, document_id, source_version_id, content_basis_digest, unit_ordinal, extractor_version)
);
CREATE INDEX IF NOT EXISTS workbench_entity_auto_discovery_state_idx
    ON workbench_entity_auto_discovery_unit(matter_id, extractor_version, state, document_id, unit_ordinal);
