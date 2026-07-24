-- Swasthya Sathi POC — SQLite schema (Phase 0).
-- SQLite for the POC; swap to Postgres later by reimplementing the repository
-- layer only (thin repository pattern, mirrors Dakhla/Midas).
--
-- Entities align with ARCHITECTURE.md section 5 / deck Slide 11. For the POC
-- the full SessionContext is also stored as JSON in `session_state` for easy
-- resume; the normalized tables below exist so the production seams are real.

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    lang        TEXT NOT NULL DEFAULT 'hi',
    operator_id TEXT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT
);

-- Full serialized SessionContext for resume/replay in the POC.
CREATE TABLE IF NOT EXISTS session_state (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    context    TEXT NOT NULL,          -- SessionContext JSON
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uploads (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    path       TEXT NOT NULL,
    sha256     TEXT,                   -- hash on store
    type       TEXT
);

-- Audit trail: type/version only, NEVER content (privacy invariant).
CREATE TABLE IF NOT EXISTS audit_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    ts         TEXT NOT NULL,
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    detail     TEXT                    -- type/version only
);

CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_events(session_id);
CREATE INDEX IF NOT EXISTS idx_uploads_session ON uploads(session_id);
