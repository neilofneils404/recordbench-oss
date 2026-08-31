PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workbench_matter (
    matter_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    descriptor TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workbench_conversation (
    conversation_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL REFERENCES workbench_matter(matter_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS workbench_conversation_matter_idx
    ON workbench_conversation(matter_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS workbench_message (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES workbench_conversation(conversation_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (conversation_id, ordinal)
);

CREATE INDEX IF NOT EXISTS workbench_message_conversation_idx
    ON workbench_message(conversation_id, ordinal);
