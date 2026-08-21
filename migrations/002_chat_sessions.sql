-- Chat history sessions.
--
-- The chat router persists each conversation as one row with the full message
-- list in JSONB; messages are only ever read/written as a whole conversation,
-- so a child table would add joins without adding queries we need.

CREATE TABLE IF NOT EXISTS chat_sessions (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    messages        JSONB NOT NULL DEFAULT '[]'::jsonb,
    lang            TEXT NOT NULL DEFAULT 'vi'
);

CREATE INDEX IF NOT EXISTS chat_sessions_updated_idx
    ON chat_sessions (updated_at DESC);
