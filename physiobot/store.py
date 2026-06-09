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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
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
                """
            )

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
