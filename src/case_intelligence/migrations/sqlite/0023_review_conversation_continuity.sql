-- SQLite cannot add a guarded foreign-key column with IF NOT EXISTS. The
-- application performs idempotent PRAGMA-guarded additions for the two
-- conversation-continuity fields after this migration marker is applied.
SELECT 1;
