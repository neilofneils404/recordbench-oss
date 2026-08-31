PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_oidc_transaction (
    state_digest TEXT PRIMARY KEY CHECK (length(state_digest) = 64),
    next_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT
);

CREATE INDEX IF NOT EXISTS workbench_oidc_transaction_expiry_idx
    ON workbench_oidc_transaction(expires_at, consumed_at);
