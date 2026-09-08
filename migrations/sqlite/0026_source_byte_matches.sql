PRAGMA foreign_keys = ON;

-- Rebuildable lookup of already admitted bytes; the source registry remains
-- authoritative. Do not add columns to the catalog decoded by older readers.
CREATE TABLE IF NOT EXISTS workbench_source_byte_match (
    matter_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
    byte_size INTEGER NOT NULL CHECK(byte_size>=0),
    PRIMARY KEY(matter_id,document_id),
    FOREIGN KEY(matter_id,document_id)
        REFERENCES workbench_source_catalog(matter_id,document_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS workbench_source_byte_match_group_idx
    ON workbench_source_byte_match(matter_id,source_sha256,byte_size,document_id);

-- A previous writer can change the catalog without updating this derived
-- lookup. Version, size and admitted state must still agree before comparison.
CREATE VIEW IF NOT EXISTS workbench_current_source_bytes AS
    SELECT b.*,c.action_token FROM workbench_source_byte_match b
    JOIN workbench_source_catalog c ON c.matter_id=b.matter_id
        AND c.document_id=b.document_id AND c.version_id=b.version_id
        AND c.byte_size=b.byte_size
    WHERE c.source_state IN ('queued','processing','ready','needs_ocr','failed','playback_only');
