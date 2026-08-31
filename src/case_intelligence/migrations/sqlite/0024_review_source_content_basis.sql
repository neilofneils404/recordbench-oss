-- SQLite cannot add guarded columns with IF NOT EXISTS. The application uses
-- PRAGMA table_info to add the content-basis fields idempotently after this
-- marker, then every new source-check snapshot records the searchable basis.
SELECT 1;
