BEGIN;

ALTER TABLE review_document DROP CONSTRAINT IF EXISTS review_document_media_type_check;
ALTER TABLE review_document ADD CONSTRAINT review_document_media_type_check
  CHECK (media_type IN (
    'application/pdf',
    'text/plain',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  ));

CREATE TABLE IF NOT EXISTS review_source_version (
  matter_id text NOT NULL,
  document_id text NOT NULL,
  source_version_id text NOT NULL,
  content_digest text NOT NULL,
  byte_size bigint NOT NULL CHECK (byte_size >= 0),
  media_type text NOT NULL CHECK (media_type IN (
    'application/pdf',
    'text/plain',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  )),
  storage_key text NOT NULL,
  status text NOT NULL CHECK (status IN ('processing','ready','needs_ocr','failed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (matter_id, document_id, source_version_id),
  UNIQUE (matter_id, document_id, content_digest),
  FOREIGN KEY (matter_id, document_id)
    REFERENCES review_document(matter_id, document_id) ON DELETE CASCADE
);

ALTER TABLE review_document ADD COLUMN IF NOT EXISTS current_source_version_id text;
ALTER TABLE review_document ALTER COLUMN current_source_version_id SET DEFAULT 'synthetic-v1';
ALTER TABLE review_page ADD COLUMN IF NOT EXISTS source_version_id text;
ALTER TABLE review_page ADD COLUMN IF NOT EXISTS line_start integer;
ALTER TABLE review_page ADD COLUMN IF NOT EXISTS line_end integer;
ALTER TABLE review_chunk ADD COLUMN IF NOT EXISTS source_version_id text;
ALTER TABLE review_chunk ADD COLUMN IF NOT EXISTS line_start integer;
ALTER TABLE review_chunk ADD COLUMN IF NOT EXISTS line_end integer;
ALTER TABLE review_chunk ADD COLUMN IF NOT EXISTS char_start integer;
ALTER TABLE review_chunk ADD COLUMN IF NOT EXISTS char_end integer;
ALTER TABLE review_chunk ADD COLUMN IF NOT EXISTS excerpt_digest text;
ALTER TABLE review_processing_state ADD COLUMN IF NOT EXISTS source_version_id text;

INSERT INTO review_source_version(
  matter_id,document_id,source_version_id,content_digest,byte_size,media_type,storage_key,status
)
SELECT matter_id,document_id,'synthetic-v1','legacy-' || matter_id || '-' || document_id,0,media_type,
       'packaged-synthetic','ready'
  FROM review_document
ON CONFLICT (matter_id,document_id,source_version_id) DO NOTHING;

UPDATE review_document SET current_source_version_id='synthetic-v1'
 WHERE current_source_version_id IS NULL;
UPDATE review_page SET source_version_id='synthetic-v1' WHERE source_version_id IS NULL;
UPDATE review_chunk SET source_version_id='synthetic-v1' WHERE source_version_id IS NULL;
UPDATE review_processing_state SET source_version_id='synthetic-v1' WHERE source_version_id IS NULL;

ALTER TABLE review_document ALTER COLUMN current_source_version_id SET NOT NULL;
ALTER TABLE review_page ALTER COLUMN source_version_id SET NOT NULL;
ALTER TABLE review_chunk ALTER COLUMN source_version_id SET NOT NULL;
ALTER TABLE review_processing_state ALTER COLUMN source_version_id SET NOT NULL;

DO $$ BEGIN
  ALTER TABLE review_document ADD CONSTRAINT review_document_current_version_fk
    FOREIGN KEY (matter_id,document_id,current_source_version_id)
    REFERENCES review_source_version(matter_id,document_id,source_version_id)
    DEFERRABLE INITIALLY DEFERRED;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE review_page ADD CONSTRAINT review_page_source_version_fk
    FOREIGN KEY (matter_id,document_id,source_version_id)
    REFERENCES review_source_version(matter_id,document_id,source_version_id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE review_chunk ADD CONSTRAINT review_chunk_source_version_fk
    FOREIGN KEY (matter_id,document_id,source_version_id)
    REFERENCES review_source_version(matter_id,document_id,source_version_id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE review_processing_state ADD CONSTRAINT review_processing_source_version_fk
    FOREIGN KEY (matter_id,document_id,source_version_id)
    REFERENCES review_source_version(matter_id,document_id,source_version_id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE review_chunk ADD CONSTRAINT review_chunk_line_bounds_check
    CHECK ((line_start IS NULL AND line_end IS NULL) OR
           (line_start > 0 AND line_end >= line_start));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE review_chunk ADD CONSTRAINT review_chunk_char_bounds_check
    CHECK ((char_start IS NULL AND char_end IS NULL) OR
           (char_start >= 0 AND char_end >= char_start));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS review_source_version_status
  ON review_source_version(matter_id,document_id,status);
INSERT INTO review_schema_migration(version) VALUES (2) ON CONFLICT DO NOTHING;
COMMIT;
