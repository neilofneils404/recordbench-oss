BEGIN;

-- Media transcript passages share the existing matter/document/chunk index.
-- Only canonical media types accepted by the upload boundary are admitted.
ALTER TABLE review_document
  DROP CONSTRAINT IF EXISTS review_document_media_type_check;
ALTER TABLE review_document
  ADD CONSTRAINT review_document_media_type_check
  CHECK (media_type IN (
    'application/pdf',
    'text/plain',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'audio/wav',
    'audio/mpeg',
    'audio/mp4',
    'audio/ogg',
    'video/mp4',
    'video/quicktime',
    'video/webm'
  ));

ALTER TABLE review_source_version
  DROP CONSTRAINT IF EXISTS review_source_version_media_type_check;
ALTER TABLE review_source_version
  ADD CONSTRAINT review_source_version_media_type_check
  CHECK (media_type IN (
    'application/pdf',
    'text/plain',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'audio/wav',
    'audio/mpeg',
    'audio/mp4',
    'audio/ogg',
    'video/mp4',
    'video/quicktime',
    'video/webm'
  ));

-- Transcript offsets are stored in the existing bounded location columns as
-- milliseconds. Unlike human line numbers, a valid recording may begin at 0.
ALTER TABLE review_chunk
  DROP CONSTRAINT IF EXISTS review_chunk_line_bounds_check;
ALTER TABLE review_chunk
  ADD CONSTRAINT review_chunk_line_bounds_check
  CHECK ((line_start IS NULL AND line_end IS NULL) OR
         (line_start >= 0 AND line_end >= line_start));

INSERT INTO review_schema_migration(version) VALUES (4) ON CONFLICT DO NOTHING;
COMMIT;
