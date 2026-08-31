BEGIN;

-- Keep the derived search index aligned with the canonical upload boundary.
-- Extended sources are deterministically extracted before their text reaches
-- these existing document/source-version tables.
ALTER TABLE review_document
  DROP CONSTRAINT IF EXISTS review_document_media_type_check;
ALTER TABLE review_document
  ADD CONSTRAINT review_document_media_type_check
  CHECK (media_type IN (
    'application/pdf',
    'text/plain',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'image/jpeg',
    'image/png',
    'image/tiff',
    'message/rfc822',
    'text/csv',
    'text/tab-separated-values',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
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
    'image/jpeg',
    'image/png',
    'image/tiff',
    'message/rfc822',
    'text/csv',
    'text/tab-separated-values',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'audio/wav',
    'audio/mpeg',
    'audio/mp4',
    'audio/ogg',
    'video/mp4',
    'video/quicktime',
    'video/webm'
  ));

INSERT INTO review_schema_migration(version) VALUES (5) ON CONFLICT DO NOTHING;
COMMIT;
