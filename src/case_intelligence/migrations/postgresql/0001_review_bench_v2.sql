BEGIN;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS review_schema_migration (
  version integer PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS review_matter (
  matter_id text PRIMARY KEY,
  display_name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS review_document (
  matter_id text NOT NULL REFERENCES review_matter(matter_id) ON DELETE CASCADE,
  document_id text NOT NULL,
  display_name text NOT NULL,
  media_type text NOT NULL CHECK (media_type = 'application/pdf'),
  page_count integer NOT NULL CHECK (page_count > 0),
  PRIMARY KEY (matter_id, document_id)
);
CREATE TABLE IF NOT EXISTS review_page (
  matter_id text NOT NULL,
  document_id text NOT NULL,
  page_id text NOT NULL,
  page_number integer NOT NULL CHECK (page_number > 0),
  text text NOT NULL,
  PRIMARY KEY (matter_id, document_id, page_id),
  UNIQUE (matter_id, document_id, page_number),
  FOREIGN KEY (matter_id, document_id)
    REFERENCES review_document(matter_id, document_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS review_processing_state (
  matter_id text NOT NULL,
  document_id text NOT NULL,
  stage text NOT NULL,
  state text NOT NULL CHECK (state IN ('queued','running','ready','failed')),
  completed_units integer NOT NULL DEFAULT 0 CHECK (completed_units >= 0),
  total_units integer NOT NULL DEFAULT 0 CHECK (total_units >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (matter_id, document_id, stage),
  FOREIGN KEY (matter_id, document_id)
    REFERENCES review_document(matter_id, document_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS review_chunk (
  matter_id text NOT NULL,
  document_id text NOT NULL,
  page_id text NOT NULL,
  chunk_id text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  text text NOT NULL,
  search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
  embedding vector(768),
  PRIMARY KEY (matter_id, document_id, chunk_id),
  UNIQUE (matter_id, document_id, page_id, ordinal),
  FOREIGN KEY (matter_id, document_id, page_id)
    REFERENCES review_page(matter_id, document_id, page_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS review_chunk_fts
  ON review_chunk USING gin (search_vector);
CREATE INDEX IF NOT EXISTS review_chunk_matter
  ON review_chunk (matter_id, document_id);
CREATE INDEX IF NOT EXISTS review_processing_matter
  ON review_processing_state (matter_id, document_id, state);
CREATE INDEX IF NOT EXISTS review_chunk_embedding_hnsw
  ON review_chunk USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL;
INSERT INTO review_schema_migration(version) VALUES (1) ON CONFLICT DO NOTHING;
COMMIT;
