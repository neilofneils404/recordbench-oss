PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_principal (
    principal_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_subject TEXT NOT NULL,
    display_name TEXT NOT NULL,
    login_name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (provider, provider_subject)
);

CREATE INDEX IF NOT EXISTS workbench_principal_active_idx
    ON workbench_principal(active, display_name, principal_id);

INSERT OR IGNORE INTO workbench_principal(
    principal_id, provider, provider_subject, display_name, login_name,
    active, created_at, last_seen_at
)
SELECT
    owner_id,
    CASE WHEN owner_id = 'development-taylor-morgan' THEN 'preview' ELSE 'legacy-preview' END,
    CASE WHEN owner_id = 'development-taylor-morgan' THEN 'taylor-morgan' ELSE owner_id END,
    CASE WHEN owner_id = 'development-taylor-morgan' THEN 'Taylor Morgan' ELSE 'Development user' END,
    owner_id,
    1,
    MIN(created_at),
    MAX(updated_at)
FROM workbench_matter
GROUP BY owner_id;

CREATE TABLE IF NOT EXISTS workbench_session (
    session_id TEXT PRIMARY KEY,
    token_digest TEXT NOT NULL UNIQUE CHECK (length(token_digest) = 64),
    principal_id TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    auth_method TEXT NOT NULL,
    application_roles TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    idle_expires_at TEXT NOT NULL,
    absolute_expires_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS workbench_session_principal_idx
    ON workbench_session(principal_id, created_at DESC);

CREATE INDEX IF NOT EXISTS workbench_session_expiry_idx
    ON workbench_session(revoked_at, idle_expires_at, absolute_expires_at);

CREATE TABLE IF NOT EXISTS workbench_matter_membership (
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    principal_id TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
    state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'revoked')),
    granted_by TEXT NOT NULL REFERENCES workbench_principal(principal_id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revoked_at TEXT,
    PRIMARY KEY (matter_id, principal_id)
);

CREATE INDEX IF NOT EXISTS workbench_membership_principal_idx
    ON workbench_matter_membership(principal_id, state, updated_at DESC);

CREATE INDEX IF NOT EXISTS workbench_membership_matter_idx
    ON workbench_matter_membership(matter_id, state, role, principal_id);

INSERT OR IGNORE INTO workbench_matter_membership(
    matter_id, principal_id, role, state, granted_by, created_at, updated_at, revoked_at
)
SELECT matter_id, owner_id, 'owner', 'active', owner_id, created_at, updated_at, NULL
FROM workbench_matter;

CREATE TABLE IF NOT EXISTS workbench_audit_event (
    event_id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    actor_principal_id TEXT REFERENCES workbench_principal(principal_id),
    session_id TEXT REFERENCES workbench_session(session_id) ON DELETE SET NULL,
    matter_id TEXT REFERENCES workbench_matter(matter_id) ON DELETE SET NULL,
    request_id TEXT NOT NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'denied', 'failure')),
    object_type TEXT,
    object_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS workbench_audit_matter_idx
    ON workbench_audit_event(matter_id, occurred_at DESC, event_id);

CREATE INDEX IF NOT EXISTS workbench_audit_actor_idx
    ON workbench_audit_event(actor_principal_id, occurred_at DESC, event_id);

CREATE INDEX IF NOT EXISTS workbench_audit_action_idx
    ON workbench_audit_event(action, occurred_at DESC, event_id);

CREATE TRIGGER IF NOT EXISTS workbench_audit_event_no_update
BEFORE UPDATE ON workbench_audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS workbench_audit_event_no_delete
BEFORE DELETE ON workbench_audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;
