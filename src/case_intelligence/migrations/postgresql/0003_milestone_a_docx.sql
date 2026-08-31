BEGIN;

ALTER TABLE review_document DROP CONSTRAINT IF EXISTS review_document_media_type_check;
ALTER TABLE review_document ADD CONSTRAINT review_document_media_type_check
  CHECK (media_type IN (
    'application/pdf',
    'text/plain',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  ));

ALTER TABLE review_source_version
  DROP CONSTRAINT IF EXISTS review_source_version_media_type_check;
ALTER TABLE review_source_version
  ADD CONSTRAINT review_source_version_media_type_check
  CHECK (media_type IN (
    'application/pdf',
    'text/plain',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  ));

INSERT INTO review_schema_migration(version) VALUES (3) ON CONFLICT DO NOTHING;
COMMIT;
