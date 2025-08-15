from __future__ import annotations

import os
import sqlite3
import threading
from typing import Literal

from app.config import MAX_MEMORY, MAX_TOTAL_MEMORY

Role = Literal["user", "assistant", "system", "tool", "reviewer"]


class MemoryStore:
    def __init__(
        self,
        db_path: str | None = None,
        max_memory: int = MAX_MEMORY,
        max_total_memory: int = MAX_TOTAL_MEMORY,
    ) -> None:
        self.path = db_path or os.path.join(os.path.dirname(__file__), "assistant_memory.db")
        self.max_memory = int(max_memory)
        self.max_total_memory = int(max_total_memory)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.path,
            check_same_thread=False,
            isolation_level=None,
            timeout=30.0,
        )
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA wal_autocheckpoint=512;")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_timestamp ON memory(user_id, timestamp)"
        )

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            return cur

    def store_message(self, user_id: str, role: Role, content: str) -> None:
        if role not in {"user", "assistant", "system", "tool", "reviewer"}:
            raise ValueError("invalid role")
        self._execute(
            "INSERT INTO memory (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content),
        )
        self.trim_user_memory(user_id)

    def get_user_memory(self, user_id: str, limit: int = MAX_MEMORY) -> list[dict[str, str]]:
        lim = max(1, int(limit))
        cur = self._execute(
            """
            SELECT role, content
            FROM memory
            WHERE user_id = ?
            ORDER BY rowid DESC
            LIMIT ?
            """,
            (user_id, lim),
        )
        rows = cur.fetchall()
        rows.reverse()
        return [{"role": r, "content": c} for r, c in rows]

    def forget_user(self, user_id: str) -> None:
        self._execute("DELETE FROM memory WHERE user_id = ?", (user_id,))

    def trim_user_memory(self, user_id: str, max_rows: int | None = None) -> None:
        cap = int(max_rows or self.max_total_memory)
        self._execute(
            """
            DELETE FROM memory
            WHERE user_id = ?
              AND rowid NOT IN (
                  SELECT rowid
                  FROM memory
                  WHERE user_id = ?
                  ORDER BY rowid DESC
                  LIMIT ?
              )
            """,
            (user_id, user_id, cap),
        )

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


_store = MemoryStore()


def store_message(user_id: str, role: Role, content: str) -> None:
    _store.store_message(user_id, role, content)


def get_user_memory(user_id: str, limit: int = MAX_MEMORY) -> list[dict[str, str]]:
    return _store.get_user_memory(user_id, limit)


def forget_user(user_id: str) -> None:
    _store.forget_user(user_id)


def trim_user_memory(user_id: str, max_rows: int = MAX_TOTAL_MEMORY) -> None:
    _store.trim_user_memory(user_id, max_rows)
