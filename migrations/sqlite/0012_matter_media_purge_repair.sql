PRAGMA foreign_keys = ON;

-- A deleted matter is a content-free receipt. Remove media rows left by an A10
-- pre-acceptance purge and enforce the same invariant for every later purge.
DELETE FROM workbench_media_clip
WHERE matter_id IN (
    SELECT matter_id FROM workbench_matter_lifecycle WHERE state = 'deleted'
);

DELETE FROM workbench_media_job
WHERE matter_id IN (
    SELECT matter_id FROM workbench_matter_lifecycle WHERE state = 'deleted'
);

CREATE TRIGGER IF NOT EXISTS workbench_deleted_matter_media_cleanup
AFTER UPDATE OF state ON workbench_matter_lifecycle
WHEN NEW.state = 'deleted'
BEGIN
    DELETE FROM workbench_media_clip WHERE matter_id = NEW.matter_id;
    DELETE FROM workbench_media_job WHERE matter_id = NEW.matter_id;
END;
