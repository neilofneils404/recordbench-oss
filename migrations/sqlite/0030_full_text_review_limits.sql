PRAGMA foreign_keys = ON;
-- Additive full-text resource receipts and constant-size coverage projections.
-- Python backfills old 0028 ledgers once before a worker can claim them.
CREATE TABLE IF NOT EXISTS workbench_text_review_budget (
    run_id TEXT PRIMARY KEY REFERENCES workbench_text_review(run_id) ON DELETE CASCADE,
    max_characters INTEGER NOT NULL CHECK(max_characters>0),
    max_calls INTEGER NOT NULL CHECK(max_calls>0),
    max_ledger_bytes INTEGER NOT NULL CHECK(max_ledger_bytes>0),
    characters_used INTEGER NOT NULL DEFAULT 0 CHECK(characters_used>=0),
    calls_used INTEGER NOT NULL DEFAULT 0 CHECK(calls_used>=0),
    ledger_bytes INTEGER NOT NULL DEFAULT 0 CHECK(ledger_bytes>=0),
    legacy INTEGER NOT NULL DEFAULT 0 CHECK(legacy IN (0,1)),
    limit_reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS workbench_text_review_counter (
    run_id TEXT NOT NULL REFERENCES workbench_text_review(run_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0 CHECK(count>=0),
    characters INTEGER NOT NULL DEFAULT 0 CHECK(characters>=0),
    PRIMARY KEY(run_id,kind,state)
);
CREATE INDEX IF NOT EXISTS workbench_text_review_source_state_idx ON workbench_text_review_source(run_id,state);

CREATE TRIGGER IF NOT EXISTS text_review_source_insert BEFORE INSERT ON workbench_text_review_source
WHEN EXISTS(SELECT 1 FROM workbench_text_review_budget WHERE run_id=NEW.run_id)
BEGIN
    SELECT CASE WHEN (SELECT ledger_bytes+(65536+length(CAST(NEW.run_id AS BLOB))+length(CAST(NEW.document_id AS BLOB))+length(CAST(NEW.source_version_id AS BLOB))+length(CAST(NEW.source_basis_digest AS BLOB))+length(CAST(NEW.source_name AS BLOB))+length(CAST(NEW.source_kind AS BLOB))+length(CAST(NEW.source_state AS BLOB))+length(CAST(NEW.extraction_note AS BLOB))+length(CAST(NEW.state AS BLOB)))>max_ledger_bytes AND legacy=0
        FROM workbench_text_review_budget WHERE run_id=NEW.run_id)
        THEN RAISE(ABORT,'full-text ledger storage limit') END;
    UPDATE workbench_text_review_budget SET ledger_bytes=ledger_bytes+(65536+length(CAST(NEW.run_id AS BLOB))+length(CAST(NEW.document_id AS BLOB))+length(CAST(NEW.source_version_id AS BLOB))+length(CAST(NEW.source_basis_digest AS BLOB))+length(CAST(NEW.source_name AS BLOB))+length(CAST(NEW.source_kind AS BLOB))+length(CAST(NEW.source_state AS BLOB))+length(CAST(NEW.extraction_note AS BLOB))+length(CAST(NEW.state AS BLOB))) WHERE run_id=NEW.run_id;
    INSERT INTO workbench_text_review_counter(run_id,kind,state,count,characters)
    VALUES (NEW.run_id,'source',NEW.state,1,(NEW.text_chars)*(1))
    ON CONFLICT(run_id,kind,state) DO UPDATE SET count=count+(1),characters=characters+(NEW.text_chars)*(1);
    INSERT INTO workbench_text_review_counter(run_id,kind,state,count,characters) VALUES(NEW.run_id,'inventory','unresolved',CASE WHEN NEW.source_state='ready' AND NEW.inventory_sealed=0 THEN 1 ELSE 0 END,0) ON CONFLICT(run_id,kind,state) DO UPDATE SET count=count+(CASE WHEN NEW.source_state='ready' AND NEW.inventory_sealed=0 THEN 1 ELSE 0 END);
INSERT INTO workbench_text_review_counter(run_id,kind,state,count,characters) VALUES(NEW.run_id,'inventory','zero_units',CASE WHEN NEW.source_state='ready' AND NEW.inventory_sealed=1 AND NEW.unit_count=0 THEN 1 ELSE 0 END,0) ON CONFLICT(run_id,kind,state) DO UPDATE SET count=count+(CASE WHEN NEW.source_state='ready' AND NEW.inventory_sealed=1 AND NEW.unit_count=0 THEN 1 ELSE 0 END);

END;
CREATE TRIGGER IF NOT EXISTS text_review_source_update BEFORE UPDATE ON workbench_text_review_source
WHEN EXISTS(SELECT 1 FROM workbench_text_review_budget WHERE run_id=NEW.run_id)
BEGIN
    SELECT CASE WHEN (SELECT ledger_bytes+(65536+length(CAST(NEW.run_id AS BLOB))+length(CAST(NEW.document_id AS BLOB))+length(CAST(NEW.source_version_id AS BLOB))+length(CAST(NEW.source_basis_digest AS BLOB))+length(CAST(NEW.source_name AS BLOB))+length(CAST(NEW.source_kind AS BLOB))+length(CAST(NEW.source_state AS BLOB))+length(CAST(NEW.extraction_note AS BLOB))+length(CAST(NEW.state AS BLOB)))-(65536+length(CAST(OLD.run_id AS BLOB))+length(CAST(OLD.document_id AS BLOB))+length(CAST(OLD.source_version_id AS BLOB))+length(CAST(OLD.source_basis_digest AS BLOB))+length(CAST(OLD.source_name AS BLOB))+length(CAST(OLD.source_kind AS BLOB))+length(CAST(OLD.source_state AS BLOB))+length(CAST(OLD.extraction_note AS BLOB))+length(CAST(OLD.state AS BLOB)))>max_ledger_bytes AND legacy=0
        FROM workbench_text_review_budget WHERE run_id=NEW.run_id)
        THEN RAISE(ABORT,'full-text ledger storage limit') END;
    UPDATE workbench_text_review_budget SET ledger_bytes=ledger_bytes+(65536+length(CAST(NEW.run_id AS BLOB))+length(CAST(NEW.document_id AS BLOB))+length(CAST(NEW.source_version_id AS BLOB))+length(CAST(NEW.source_basis_digest AS BLOB))+length(CAST(NEW.source_name AS BLOB))+length(CAST(NEW.source_kind AS BLOB))+length(CAST(NEW.source_state AS BLOB))+length(CAST(NEW.extraction_note AS BLOB))+length(CAST(NEW.state AS BLOB)))-(65536+length(CAST(OLD.run_id AS BLOB))+length(CAST(OLD.document_id AS BLOB))+length(CAST(OLD.source_version_id AS BLOB))+length(CAST(OLD.source_basis_digest AS BLOB))+length(CAST(OLD.source_name AS BLOB))+length(CAST(OLD.source_kind AS BLOB))+length(CAST(OLD.source_state AS BLOB))+length(CAST(OLD.extraction_note AS BLOB))+length(CAST(OLD.state AS BLOB))) WHERE run_id=NEW.run_id;
    UPDATE workbench_text_review_counter SET count=count-1,characters=characters-(OLD.text_chars)
    WHERE run_id=OLD.run_id AND kind='source' AND state=OLD.state;
    INSERT INTO workbench_text_review_counter(run_id,kind,state,count,characters)
    VALUES (NEW.run_id,'source',NEW.state,1,(NEW.text_chars)*(1))
    ON CONFLICT(run_id,kind,state) DO UPDATE SET count=count+(1),characters=characters+(NEW.text_chars)*(1);
    UPDATE workbench_text_review_counter SET count=count-(CASE WHEN OLD.source_state='ready' AND OLD.inventory_sealed=0 THEN 1 ELSE 0 END) WHERE run_id=OLD.run_id AND kind='inventory' AND state='unresolved';
UPDATE workbench_text_review_counter SET count=count-(CASE WHEN OLD.source_state='ready' AND OLD.inventory_sealed=1 AND OLD.unit_count=0 THEN 1 ELSE 0 END) WHERE run_id=OLD.run_id AND kind='inventory' AND state='zero_units';
INSERT INTO workbench_text_review_counter(run_id,kind,state,count,characters) VALUES(NEW.run_id,'inventory','unresolved',CASE WHEN NEW.source_state='ready' AND NEW.inventory_sealed=0 THEN 1 ELSE 0 END,0) ON CONFLICT(run_id,kind,state) DO UPDATE SET count=count+(CASE WHEN NEW.source_state='ready' AND NEW.inventory_sealed=0 THEN 1 ELSE 0 END);
INSERT INTO workbench_text_review_counter(run_id,kind,state,count,characters) VALUES(NEW.run_id,'inventory','zero_units',CASE WHEN NEW.source_state='ready' AND NEW.inventory_sealed=1 AND NEW.unit_count=0 THEN 1 ELSE 0 END,0) ON CONFLICT(run_id,kind,state) DO UPDATE SET count=count+(CASE WHEN NEW.source_state='ready' AND NEW.inventory_sealed=1 AND NEW.unit_count=0 THEN 1 ELSE 0 END);

END;
CREATE TRIGGER IF NOT EXISTS text_review_source_delete BEFORE DELETE ON workbench_text_review_source
BEGIN
    UPDATE workbench_text_review_budget SET ledger_bytes=ledger_bytes-(65536+length(CAST(OLD.run_id AS BLOB))+length(CAST(OLD.document_id AS BLOB))+length(CAST(OLD.source_version_id AS BLOB))+length(CAST(OLD.source_basis_digest AS BLOB))+length(CAST(OLD.source_name AS BLOB))+length(CAST(OLD.source_kind AS BLOB))+length(CAST(OLD.source_state AS BLOB))+length(CAST(OLD.extraction_note AS BLOB))+length(CAST(OLD.state AS BLOB))) WHERE run_id=OLD.run_id;
    UPDATE workbench_text_review_counter SET count=count-1,characters=characters-(OLD.text_chars)
    WHERE run_id=OLD.run_id AND kind='source' AND state=OLD.state;
    UPDATE workbench_text_review_counter SET count=count-(CASE WHEN OLD.source_state='ready' AND OLD.inventory_sealed=0 THEN 1 ELSE 0 END) WHERE run_id=OLD.run_id AND kind='inventory' AND state='unresolved';
UPDATE workbench_text_review_counter SET count=count-(CASE WHEN OLD.source_state='ready' AND OLD.inventory_sealed=1 AND OLD.unit_count=0 THEN 1 ELSE 0 END) WHERE run_id=OLD.run_id AND kind='inventory' AND state='zero_units';

END;

CREATE TRIGGER IF NOT EXISTS text_review_unit_insert BEFORE INSERT ON workbench_text_review_unit
WHEN EXISTS(SELECT 1 FROM workbench_text_review_budget WHERE run_id=NEW.run_id)
BEGIN
    SELECT CASE WHEN (SELECT ledger_bytes+(512+length(CAST(NEW.run_id AS BLOB))+length(CAST(NEW.document_id AS BLOB))+length(CAST(NEW.location AS BLOB))+length(CAST(NEW.unit_digest AS BLOB))+length(CAST(NEW.state AS BLOB))+length(CAST(NEW.citation_json AS BLOB)))>max_ledger_bytes AND legacy=0
        FROM workbench_text_review_budget WHERE run_id=NEW.run_id)
        THEN RAISE(ABORT,'full-text ledger storage limit') END;
    UPDATE workbench_text_review_budget SET characters_used=characters_used+NEW.text_chars WHERE run_id=NEW.run_id;
    UPDATE workbench_text_review_budget SET ledger_bytes=ledger_bytes+(512+length(CAST(NEW.run_id AS BLOB))+length(CAST(NEW.document_id AS BLOB))+length(CAST(NEW.location AS BLOB))+length(CAST(NEW.unit_digest AS BLOB))+length(CAST(NEW.state AS BLOB))+length(CAST(NEW.citation_json AS BLOB))) WHERE run_id=NEW.run_id;
    INSERT INTO workbench_text_review_counter(run_id,kind,state,count,characters)
    VALUES (NEW.run_id,'unit',NEW.state,1,(NEW.text_chars)*(1))
    ON CONFLICT(run_id,kind,state) DO UPDATE SET count=count+(1),characters=characters+(NEW.text_chars)*(1);
    
END;
CREATE TRIGGER IF NOT EXISTS text_review_unit_update BEFORE UPDATE ON workbench_text_review_unit
WHEN EXISTS(SELECT 1 FROM workbench_text_review_budget WHERE run_id=NEW.run_id)
BEGIN
    SELECT CASE WHEN (SELECT ledger_bytes+(512+length(CAST(NEW.run_id AS BLOB))+length(CAST(NEW.document_id AS BLOB))+length(CAST(NEW.location AS BLOB))+length(CAST(NEW.unit_digest AS BLOB))+length(CAST(NEW.state AS BLOB))+length(CAST(NEW.citation_json AS BLOB)))-(512+length(CAST(OLD.run_id AS BLOB))+length(CAST(OLD.document_id AS BLOB))+length(CAST(OLD.location AS BLOB))+length(CAST(OLD.unit_digest AS BLOB))+length(CAST(OLD.state AS BLOB))+length(CAST(OLD.citation_json AS BLOB)))>max_ledger_bytes AND legacy=0
        FROM workbench_text_review_budget WHERE run_id=NEW.run_id)
        THEN RAISE(ABORT,'full-text ledger storage limit') END;
    UPDATE workbench_text_review_budget SET characters_used=characters_used+NEW.text_chars-OLD.text_chars WHERE run_id=NEW.run_id;
    UPDATE workbench_text_review_budget SET ledger_bytes=ledger_bytes+(512+length(CAST(NEW.run_id AS BLOB))+length(CAST(NEW.document_id AS BLOB))+length(CAST(NEW.location AS BLOB))+length(CAST(NEW.unit_digest AS BLOB))+length(CAST(NEW.state AS BLOB))+length(CAST(NEW.citation_json AS BLOB)))-(512+length(CAST(OLD.run_id AS BLOB))+length(CAST(OLD.document_id AS BLOB))+length(CAST(OLD.location AS BLOB))+length(CAST(OLD.unit_digest AS BLOB))+length(CAST(OLD.state AS BLOB))+length(CAST(OLD.citation_json AS BLOB))) WHERE run_id=NEW.run_id;
    UPDATE workbench_text_review_counter SET count=count-1,characters=characters-(OLD.text_chars)
    WHERE run_id=OLD.run_id AND kind='unit' AND state=OLD.state;
    INSERT INTO workbench_text_review_counter(run_id,kind,state,count,characters)
    VALUES (NEW.run_id,'unit',NEW.state,1,(NEW.text_chars)*(1))
    ON CONFLICT(run_id,kind,state) DO UPDATE SET count=count+(1),characters=characters+(NEW.text_chars)*(1);
    
END;
CREATE TRIGGER IF NOT EXISTS text_review_unit_delete BEFORE DELETE ON workbench_text_review_unit
BEGIN
    UPDATE workbench_text_review_budget SET characters_used=characters_used-OLD.text_chars WHERE run_id=OLD.run_id;
    UPDATE workbench_text_review_budget SET ledger_bytes=ledger_bytes-(512+length(CAST(OLD.run_id AS BLOB))+length(CAST(OLD.document_id AS BLOB))+length(CAST(OLD.location AS BLOB))+length(CAST(OLD.unit_digest AS BLOB))+length(CAST(OLD.state AS BLOB))+length(CAST(OLD.citation_json AS BLOB))) WHERE run_id=OLD.run_id;
    UPDATE workbench_text_review_counter SET count=count-1,characters=characters-(OLD.text_chars)
    WHERE run_id=OLD.run_id AND kind='unit' AND state=OLD.state;
    
END;

CREATE TRIGGER IF NOT EXISTS text_review_chunk_insert BEFORE INSERT ON workbench_text_review_chunk
WHEN EXISTS(SELECT 1 FROM workbench_text_review_budget WHERE run_id=NEW.run_id)
BEGIN
    SELECT CASE WHEN (SELECT ledger_bytes+(512+length(CAST(NEW.run_id AS BLOB))+length(CAST(NEW.document_id AS BLOB))+length(CAST(NEW.state AS BLOB))+length(CAST(NEW.decision AS BLOB))+length(CAST(NEW.rationale AS BLOB))+length(CAST(NEW.finding_key AS BLOB)))>max_ledger_bytes AND legacy=0
        FROM workbench_text_review_budget WHERE run_id=NEW.run_id)
        THEN RAISE(ABORT,'full-text ledger storage limit') END;
    UPDATE workbench_text_review_budget SET ledger_bytes=ledger_bytes+(512+length(CAST(NEW.run_id AS BLOB))+length(CAST(NEW.document_id AS BLOB))+length(CAST(NEW.state AS BLOB))+length(CAST(NEW.decision AS BLOB))+length(CAST(NEW.rationale AS BLOB))+length(CAST(NEW.finding_key AS BLOB))) WHERE run_id=NEW.run_id;
    INSERT INTO workbench_text_review_counter(run_id,kind,state,count,characters)
    VALUES (NEW.run_id,'chunk',NEW.state,1,(NEW.coverage_end-NEW.coverage_start)*(1))
    ON CONFLICT(run_id,kind,state) DO UPDATE SET count=count+(1),characters=characters+(NEW.coverage_end-NEW.coverage_start)*(1);
    
END;
CREATE TRIGGER IF NOT EXISTS text_review_chunk_update BEFORE UPDATE ON workbench_text_review_chunk
WHEN EXISTS(SELECT 1 FROM workbench_text_review_budget WHERE run_id=NEW.run_id)
BEGIN
    SELECT CASE WHEN (SELECT ledger_bytes+(512+length(CAST(NEW.run_id AS BLOB))+length(CAST(NEW.document_id AS BLOB))+length(CAST(NEW.state AS BLOB))+length(CAST(NEW.decision AS BLOB))+length(CAST(NEW.rationale AS BLOB))+length(CAST(NEW.finding_key AS BLOB)))-(512+length(CAST(OLD.run_id AS BLOB))+length(CAST(OLD.document_id AS BLOB))+length(CAST(OLD.state AS BLOB))+length(CAST(OLD.decision AS BLOB))+length(CAST(OLD.rationale AS BLOB))+length(CAST(OLD.finding_key AS BLOB)))>max_ledger_bytes AND legacy=0
        FROM workbench_text_review_budget WHERE run_id=NEW.run_id)
        THEN RAISE(ABORT,'full-text ledger storage limit') END;
    UPDATE workbench_text_review_budget SET ledger_bytes=ledger_bytes+(512+length(CAST(NEW.run_id AS BLOB))+length(CAST(NEW.document_id AS BLOB))+length(CAST(NEW.state AS BLOB))+length(CAST(NEW.decision AS BLOB))+length(CAST(NEW.rationale AS BLOB))+length(CAST(NEW.finding_key AS BLOB)))-(512+length(CAST(OLD.run_id AS BLOB))+length(CAST(OLD.document_id AS BLOB))+length(CAST(OLD.state AS BLOB))+length(CAST(OLD.decision AS BLOB))+length(CAST(OLD.rationale AS BLOB))+length(CAST(OLD.finding_key AS BLOB))) WHERE run_id=NEW.run_id;
    UPDATE workbench_text_review_counter SET count=count-1,characters=characters-(OLD.coverage_end-OLD.coverage_start)
    WHERE run_id=OLD.run_id AND kind='chunk' AND state=OLD.state;
    INSERT INTO workbench_text_review_counter(run_id,kind,state,count,characters)
    VALUES (NEW.run_id,'chunk',NEW.state,1,(NEW.coverage_end-NEW.coverage_start)*(1))
    ON CONFLICT(run_id,kind,state) DO UPDATE SET count=count+(1),characters=characters+(NEW.coverage_end-NEW.coverage_start)*(1);
    
END;
CREATE TRIGGER IF NOT EXISTS text_review_chunk_delete BEFORE DELETE ON workbench_text_review_chunk
BEGIN
    UPDATE workbench_text_review_budget SET ledger_bytes=ledger_bytes-(512+length(CAST(OLD.run_id AS BLOB))+length(CAST(OLD.document_id AS BLOB))+length(CAST(OLD.state AS BLOB))+length(CAST(OLD.decision AS BLOB))+length(CAST(OLD.rationale AS BLOB))+length(CAST(OLD.finding_key AS BLOB))) WHERE run_id=OLD.run_id;
    UPDATE workbench_text_review_counter SET count=count-1,characters=characters-(OLD.coverage_end-OLD.coverage_start)
    WHERE run_id=OLD.run_id AND kind='chunk' AND state=OLD.state;
    
END;
