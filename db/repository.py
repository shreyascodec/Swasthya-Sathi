"""SessionRepository — the only module that talks to the database.

Keeps SQLite behind a small interface so a later swap to Postgres/Supabase
touches one file. Persists the full SessionContext as JSON for POC resume, plus
normalized session / upload / audit rows for the production seam.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.context import SessionContext

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "swasthya_poc.sqlite3"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionRepository:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = str(db_path)
        # Streamlit reruns execute on different threads while the repository is
        # cached process-wide; the RLock serializes access to the shared handle.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
            self._conn.executescript(fh.read())
        self._conn.commit()

    # -- sessions ---------------------------------------------------------
    def create_session(self, ctx: SessionContext, operator_id: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO sessions (id, lang, operator_id, started_at) "
                "VALUES (?, ?, ?, ?)",
                (ctx.session_id, ctx.lang, operator_id, _utcnow_iso()),
            )
            self._conn.commit()

    def save_context(self, ctx: SessionContext) -> None:
        """Upsert the serialized context and mirror the audit trail."""
        with self._lock:
            self.create_session(ctx)
            self._conn.execute(
                "INSERT INTO session_state (session_id, context, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET context=excluded.context, "
                "updated_at=excluded.updated_at",
                (ctx.session_id, ctx.model_dump_json(), _utcnow_iso()),
            )
            self._sync_audit(ctx)
            self._sync_uploads(ctx)
            self._conn.commit()

    def load_context(self, session_id: str) -> SessionContext | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT context FROM session_state WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionContext.model_validate_json(row["context"])

    def list_sessions(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM sessions ORDER BY started_at DESC"
            ).fetchall()
        return [r["id"] for r in rows]

    # -- audit ------------------------------------------------------------
    def _sync_audit(self, ctx: SessionContext) -> None:
        """Replace this session's audit rows with the context's current trail."""
        self._conn.execute(
            "DELETE FROM audit_events WHERE session_id = ?", (ctx.session_id,)
        )
        self._conn.executemany(
            "INSERT INTO audit_events (session_id, ts, actor, action, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (ctx.session_id, e.ts.isoformat(), e.actor, e.action, e.detail)
                for e in ctx.audit
            ],
        )

    def _sync_uploads(self, ctx: SessionContext) -> None:
        """Mirror ctx.uploads into the normalized uploads table (hash on store)."""
        self._conn.execute(
            "DELETE FROM uploads WHERE session_id = ?", (ctx.session_id,)
        )
        self._conn.executemany(
            "INSERT INTO uploads (id, session_id, path, sha256, type) "
            "VALUES (?, ?, ?, ?, ?)",
            [(u.id, ctx.session_id, u.path, u.sha256, u.type) for u in ctx.uploads],
        )

    def close(self) -> None:
        self._conn.close()
