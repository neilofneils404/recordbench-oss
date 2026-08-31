PRAGMA foreign_keys = ON;

CREATE TABLE schema_migration (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
CREATE TABLE matter_catalog (
  matter_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL
);
CREATE TABLE source_location (
  source_location_id TEXT PRIMARY KEY,
  matter_id TEXT NOT NULL REFERENCES matter_catalog(matter_id),
  display_name TEXT NOT NULL,
  enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
  catalog_revision INTEGER NOT NULL DEFAULT 0 CHECK(catalog_revision >= 0),
  UNIQUE(matter_id, source_location_id)
);
CREATE TABLE scanner_binding (
  source_location_id TEXT PRIMARY KEY REFERENCES source_location(source_location_id),
  matter_id TEXT NOT NULL,
  synthetic_root TEXT NOT NULL,
  binding_revision INTEGER NOT NULL CHECK(binding_revision >= 1),
  FOREIGN KEY(matter_id, source_location_id) REFERENCES source_location(matter_id, source_location_id)
);
CREATE TABLE windows_mapping (
  source_location_id TEXT PRIMARY KEY REFERENCES source_location(source_location_id),
  matter_id TEXT NOT NULL,
  canonical_unc_root TEXT NOT NULL,
  mapping_revision INTEGER NOT NULL CHECK(mapping_revision >= 1),
  FOREIGN KEY(matter_id, source_location_id) REFERENCES source_location(matter_id, source_location_id)
);
CREATE TABLE source_file (
  source_file_id TEXT PRIMARY KEY,
  matter_id TEXT NOT NULL,
  source_location_id TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  display_name TEXT NOT NULL,
  media_type TEXT NOT NULL,
  availability TEXT NOT NULL CHECK(availability IN ('available','missing')),
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  current_source_version_id TEXT,
  UNIQUE(matter_id, source_location_id, relative_path),
  UNIQUE(matter_id, source_file_id),
  FOREIGN KEY(matter_id, source_location_id) REFERENCES source_location(matter_id, source_location_id)
);
CREATE TABLE source_version (
  source_version_id TEXT PRIMARY KEY,
  source_file_id TEXT NOT NULL REFERENCES source_file(source_file_id),
  matter_id TEXT NOT NULL,
  source_location_id TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  display_name TEXT NOT NULL,
  media_type TEXT NOT NULL,
  byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  stable_device INTEGER NOT NULL,
  stable_inode INTEGER NOT NULL,
  stable_mtime_ns INTEGER NOT NULL,
  discovered_at TEXT NOT NULL,
  UNIQUE(source_file_id, sha256),
  UNIQUE(matter_id, source_version_id),
  UNIQUE(matter_id, source_file_id, source_version_id),
  FOREIGN KEY(matter_id, source_file_id) REFERENCES source_file(matter_id, source_file_id)
);
CREATE TABLE scan_run (
  scan_run_id TEXT PRIMARY KEY,
  matter_id TEXT NOT NULL REFERENCES matter_catalog(matter_id),
  source_location_id TEXT NOT NULL,
  scan_idempotency_key TEXT NOT NULL,
  captured_catalog_revision INTEGER NOT NULL,
  binding_revision INTEGER NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('running','succeeded','failed','superseded')),
  failure_category TEXT,
  created_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(source_location_id, scan_idempotency_key),
  UNIQUE(scan_run_id, matter_id),
  FOREIGN KEY(matter_id, source_location_id) REFERENCES source_location(matter_id, source_location_id)
);
CREATE TABLE scan_attempt (
  scan_attempt_id TEXT PRIMARY KEY,
  scan_run_id TEXT NOT NULL REFERENCES scan_run(scan_run_id),
  attempt_number INTEGER NOT NULL CHECK(attempt_number >= 1),
  state TEXT NOT NULL CHECK(state IN ('running','succeeded','failed','superseded')),
  failure_category TEXT,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(scan_run_id, attempt_number)
);
CREATE TABLE scan_observation (
  scan_run_id TEXT NOT NULL REFERENCES scan_run(scan_run_id),
  matter_id TEXT NOT NULL,
  source_file_id TEXT NOT NULL,
  source_version_id TEXT NOT NULL,
  PRIMARY KEY(scan_run_id, source_file_id),
  FOREIGN KEY(scan_run_id, matter_id) REFERENCES scan_run(scan_run_id, matter_id),
  FOREIGN KEY(matter_id, source_file_id) REFERENCES source_file(matter_id, source_file_id),
  FOREIGN KEY(matter_id, source_version_id) REFERENCES source_version(matter_id, source_version_id)
);
CREATE TABLE job (
  job_id TEXT PRIMARY KEY,
  matter_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  source_version_id TEXT NOT NULL,
  processor_version TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('queued','running','succeeded','failed','not_processed')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(kind, source_version_id, processor_version),
  FOREIGN KEY(matter_id, source_version_id) REFERENCES source_version(matter_id, source_version_id)
);
CREATE TABLE job_attempt (
  job_attempt_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES job(job_id),
  attempt_number INTEGER NOT NULL CHECK(attempt_number >= 1),
  state TEXT NOT NULL CHECK(state IN ('running','succeeded','failed','superseded')),
  failure_category TEXT,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(job_id, attempt_number)
);
CREATE TABLE representation (
  representation_id TEXT PRIMARY KEY,
  matter_id TEXT NOT NULL,
  source_file_id TEXT NOT NULL,
  source_version_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind='plain_text'),
  processor_version TEXT NOT NULL,
  text_sha256 TEXT NOT NULL CHECK(length(text_sha256)=64),
  UNIQUE(source_version_id, kind, processor_version),
  UNIQUE(matter_id, representation_id),
  UNIQUE(matter_id, source_file_id, source_version_id, representation_id),
  FOREIGN KEY(matter_id, source_file_id) REFERENCES source_file(matter_id, source_file_id),
  FOREIGN KEY(matter_id, source_file_id, source_version_id) REFERENCES source_version(matter_id, source_file_id, source_version_id)
);
CREATE TABLE segment (
  segment_id TEXT PRIMARY KEY,
  matter_id TEXT NOT NULL,
  source_file_id TEXT NOT NULL,
  source_version_id TEXT NOT NULL,
  representation_id TEXT NOT NULL REFERENCES representation(representation_id),
  ordinal INTEGER NOT NULL,
  text TEXT NOT NULL,
  text_sha256 TEXT NOT NULL CHECK(length(text_sha256)=64),
  character_start INTEGER NOT NULL,
  character_end INTEGER NOT NULL,
  line_start INTEGER NOT NULL,
  line_end INTEGER NOT NULL,
  exact_keys_json TEXT NOT NULL,
  UNIQUE(matter_id, segment_id),
  UNIQUE(representation_id, ordinal),
  FOREIGN KEY(matter_id, source_file_id) REFERENCES source_file(matter_id, source_file_id),
  FOREIGN KEY(matter_id, source_file_id, source_version_id) REFERENCES source_version(matter_id, source_file_id, source_version_id),
  FOREIGN KEY(matter_id, source_file_id, source_version_id, representation_id) REFERENCES representation(matter_id, source_file_id, source_version_id, representation_id)
);
CREATE INDEX segment_matter_version ON segment(matter_id, source_version_id);
