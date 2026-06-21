"""SQLite-backed conversation memory: sessions + message history.

The entire "memory" of the bot lives here. One row per message turn, keyed by
the patient's WhatsApp phone number.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "physiobot.db"

# How many recent turns to feed back to the model as context.
HISTORY_LIMIT = 20


class Store:
    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self.db_path = str(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        # Re-create the schema on every connection (cheap: CREATE TABLE IF NOT
        # EXISTS), not just once at construction. The db file lives outside the
        # process and can be deleted/replaced while this object is still alive
        # (e.g. an ops cleanup) — without this, the next query would crash with
        # "no such table" instead of self-healing.
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self._init_schema(conn)
        return conn

    def _init_schema(self, conn: sqlite3.Connection | None = None) -> None:
        own_conn = conn is None
        if own_conn:
            conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    phone       TEXT PRIMARY KEY,
                    state       TEXT NOT NULL DEFAULT 'active',
                    updated_at  REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone   TEXT NOT NULL,
                    role    TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts      REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_phone ON messages(phone, id);
                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_id   TEXT PRIMARY KEY,
                    processed_at REAL NOT NULL
                );
                """
            )
            conn.commit()
        finally:
            if own_conn:
                conn.close()

    def mark_processed(self, message_id: str) -> bool:
        """Atomically claim a Meta message id for processing. Returns True the
        first time it's seen, False on any later (duplicate) delivery — Meta
        retries a webhook until it gets a 200, so the same inbound message can
        arrive several times and must not be answered/booked twice.

        Always returns True for a falsy id (e.g. /simulate has no message id),
        so non-webhook callers are never deduped."""
        if not message_id:
            return True
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO processed_messages (message_id, processed_at) VALUES (?, ?)",
                (message_id, time.time()),
            )
            return cur.rowcount > 0

    def touch_session(self, phone: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (phone, state, updated_at)
                VALUES (?, 'active', ?)
                ON CONFLICT(phone) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (phone, time.time()),
            )

    def add_message(self, phone: str, role: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (phone, role, content, ts) VALUES (?, ?, ?, ?)",
                (phone, role, content, time.time()),
            )

    def history(self, phone: str, limit: int = HISTORY_LIMIT) -> list[dict]:
        """Return the most recent turns in chronological order as
        [{"role": ..., "content": ...}, ...] for the LLM."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE phone = ? "
                "ORDER BY id DESC LIMIT ?",
                (phone, limit),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
