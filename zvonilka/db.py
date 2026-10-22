"""Local SQLite storage: owner memory, chat sessions, scheduled calls."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from zvonilka.models import CallRequest, ScheduledCall

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    owner TEXT PRIMARY KEY,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    chat_id INTEGER PRIMARY KEY,
    messages TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scheduled_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    run_at TEXT NOT NULL,
    status TEXT NOT NULL,
    request TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Single owner for now; issue #1 turns this into a per-user key.
OWNER_KEY = "owner"


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # Memory (spec 7.2)

    def get_memory(self) -> str:
        row = self._conn.execute("SELECT text FROM memory WHERE owner = ?", (OWNER_KEY,)).fetchone()
        return row["text"] if row else ""

    def set_memory(self, text: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO memory (owner, text) VALUES (?, ?) "
                "ON CONFLICT(owner) DO UPDATE SET text = excluded.text",
                (OWNER_KEY, text),
            )

    # Sessions (spec 5.1)

    def load_session(self, chat_id: int) -> tuple[list[dict], datetime | None]:
        row = self._conn.execute(
            "SELECT messages, updated_at FROM sessions WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        if not row:
            return [], None
        return json.loads(row["messages"]), datetime.fromisoformat(row["updated_at"])

    def save_session(self, chat_id: int, messages: list[dict], updated_at: datetime) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO sessions (chat_id, messages, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET messages = excluded.messages, updated_at = excluded.updated_at",
                (chat_id, json.dumps(messages, ensure_ascii=False), updated_at.isoformat()),
            )

    # Scheduled calls (spec 8)

    def add_scheduled(self, chat_id: int, run_at: datetime, request: CallRequest) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO scheduled_calls (chat_id, run_at, status, request, created_at) "
                "VALUES (?, ?, 'pending', ?, ?)",
                (chat_id, run_at.astimezone(UTC).isoformat(), request.to_json(), datetime.now(UTC).isoformat()),
            )
        return cur.lastrowid

    def get_scheduled(self, call_id: int) -> ScheduledCall | None:
        row = self._conn.execute("SELECT * FROM scheduled_calls WHERE id = ?", (call_id,)).fetchone()
        return _scheduled(row) if row else None

    def scheduled_by_status(self, status: str, chat_id: int | None = None) -> list[ScheduledCall]:
        query = "SELECT * FROM scheduled_calls WHERE status = ?"
        params: tuple = (status,)
        if chat_id is not None:
            query += " AND chat_id = ?"
            params += (chat_id,)
        rows = self._conn.execute(query + " ORDER BY run_at", params).fetchall()
        return [_scheduled(row) for row in rows]

    def set_scheduled_status(self, call_id: int, status: str) -> None:
        with self._conn:
            self._conn.execute("UPDATE scheduled_calls SET status = ? WHERE id = ?", (status, call_id))


def _scheduled(row: sqlite3.Row) -> ScheduledCall:
    return ScheduledCall(
        id=row["id"],
        chat_id=row["chat_id"],
        run_at=datetime.fromisoformat(row["run_at"]),
        status=row["status"],
        request=CallRequest.from_json(row["request"]),
    )
