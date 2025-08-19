from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import aiosqlite

from app.core.config import MAX_MEMORY, MAX_TOTAL_MEMORY
from src.app.core.loging import get_logger

logger = get_logger(__name__)

Role = Literal["user", "assistant", "system", "tool", "reviewer"]


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    REVIEWER = "reviewer"


@dataclass
class Message:
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class AsyncMemoryStore:
    def __init__(
        self,
        db_path: Path | str | None = None,
        max_memory: int = MAX_MEMORY,
        max_total_memory: int = MAX_TOTAL_MEMORY,
        pool_size: int = 5,
    ):
        self.db_path = Path(db_path) if db_path else Path.home() / ".devops_ai" / "memory.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_memory = int(max_memory)
        self.max_total_memory = int(max_total_memory)
        self.pool_size = int(pool_size)
        self._pool: list[aiosqlite.Connection] = []
        self._pool_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._pool_lock:
            if self._initialized:
                return
            async with aiosqlite.connect(str(self.db_path)) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA synchronous=NORMAL")
                await db.execute("PRAGMA wal_autocheckpoint=512")
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        metadata TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_user_timestamp "
                    "ON messages(user_id, timestamp DESC)"
                )
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_user_created "
                    "ON messages(user_id, created_at DESC)"
                )
                await db.commit()
            for _ in range(self.pool_size):
                conn = await aiosqlite.connect(str(self.db_path))
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA synchronous=NORMAL")
                self._pool.append(conn)
            self._initialized = True
            logger.info(f"initialized memory store pool_size={self.pool_size}")

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        await self.initialize()
        while True:
            async with self._pool_lock:
                if self._pool:
                    conn: aiosqlite.Connection = self._pool.pop()
                    break
            await asyncio.sleep(0.01)
        try:
            yield conn
        finally:
            async with self._pool_lock:
                self._pool.append(conn)

    async def store_message(
        self,
        user_id: str,
        role: MessageRole | str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if isinstance(role, str):
            role = MessageRole(role)
        metadata_json = json.dumps(metadata) if metadata else None
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO messages (user_id, role, content, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, role.value, content, metadata_json),
            )
            await conn.commit()
            message_id_raw = cursor.lastrowid
        if message_id_raw is None:
            raise RuntimeError("insert failed: no row id returned")
        message_id = int(message_id_raw)
        await self.trim_user_memory(user_id)
        logger.debug(f"stored message id={message_id} user_id={user_id}")
        return message_id

    async def get_user_memory(
        self,
        user_id: str,
        limit: int | None = None,
        include_metadata: bool = False,
    ) -> list[dict[str, Any]]:
        lim = int(limit if limit is not None else self.max_memory)
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT role, content, metadata, timestamp
                FROM messages
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, lim),
            )
            rows_list = list(await cursor.fetchall())
        rows_list.reverse()
        messages: list[dict[str, Any]] = []
        for role, content, meta, ts in rows_list:
            msg: dict[str, Any] = {"role": role, "content": content}
            if include_metadata:
                msg["metadata"] = json.loads(meta) if meta else {}
                msg["timestamp"] = ts
            messages.append(msg)
        return messages

    async def get_message_count(self, user_id: str) -> int:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM messages WHERE user_id = ?",
                (user_id,),
            )
            result = await cursor.fetchone()
            return int(result[0] if result else 0)

    async def search_messages(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT role, content, timestamp
                FROM messages
                WHERE user_id = ? AND content LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, f"%{query}%", int(limit)),
            )
            rows = await cursor.fetchall()
        return [{"role": r, "content": c, "timestamp": t} for r, c, t in rows]

    async def trim_user_memory(
        self,
        user_id: str,
        max_rows: int | None = None,
    ) -> int:
        cap = int(max_rows if max_rows is not None else self.max_total_memory)
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """
                DELETE FROM messages
                WHERE user_id = ?
                  AND id NOT IN (
                      SELECT id
                      FROM messages
                      WHERE user_id = ?
                      ORDER BY created_at DESC
                      LIMIT ?
                  )
                """,
                (user_id, user_id, cap),
            )
            await conn.commit()
            deleted = int(cursor.rowcount or 0)
        if deleted > 0:
            logger.info(f"trimmed {deleted} messages for user_id={user_id}")
        return deleted

    async def forget_user(self, user_id: str) -> int:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM messages WHERE user_id = ?",
                (user_id,),
            )
            await conn.commit()
            deleted = int(cursor.rowcount or 0)
        logger.info(f"deleted {deleted} messages for user_id={user_id}")
        return deleted

    async def get_statistics(self) -> dict[str, Any]:
        async with self.get_connection() as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM messages")
            row = await cursor.fetchone()
            total_messages = int(row[0]) if row else 0
            cursor = await conn.execute("SELECT COUNT(DISTINCT user_id) FROM messages")
            row = await cursor.fetchone()
            unique_users = int(row[0]) if row else 0
            cursor = await conn.execute("SELECT role, COUNT(*) FROM messages GROUP BY role")
            role_distribution = {r[0]: r[1] for r in await cursor.fetchall()}
            cursor = await conn.execute("PRAGMA page_count")
            row = await cursor.fetchone()
            page_count = int(row[0]) if row else 0
            cursor = await conn.execute("PRAGMA page_size")
            row = await cursor.fetchone()
            page_size = int(row[0]) if row else 0
            db_size = page_count * page_size
        return {
            "total_messages": total_messages,
            "unique_users": unique_users,
            "role_distribution": role_distribution,
            "database_size_bytes": db_size,
            "pool_size": self.pool_size,
            "max_memory": self.max_memory,
            "max_total_memory": self.max_total_memory,
        }

    async def export_user_data(self, user_id: str) -> dict[str, Any]:
        messages = await self.get_user_memory(user_id, limit=None, include_metadata=True)
        count = await self.get_message_count(user_id)
        return {
            "user_id": user_id,
            "message_count": count,
            "messages": messages,
            "exported_at": datetime.utcnow().isoformat(),
        }

    async def close(self) -> None:
        async with self._pool_lock:
            for conn in self._pool:
                await conn.close()
            self._pool.clear()
            self._initialized = False
        logger.info("closed memory store connections")


class SyncMemoryStore:
    def __init__(
        self,
        db_path: Path | str | None = None,
        max_memory: int = MAX_MEMORY,
        max_total_memory: int = MAX_TOTAL_MEMORY,
    ):
        self.db_path = Path(db_path) if db_path else Path.home() / ".devops_ai" / "memory_sync.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_memory = int(max_memory)
        self.max_total_memory = int(max_total_memory)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._initialize()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("database connection is not initialized")
        return self._conn

    def _initialize(self) -> None:
        with self._lock:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                isolation_level=None,
                timeout=30.0,
            )
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_timestamp ON messages(user_id, timestamp DESC)"
            )

    def store_message(
        self,
        user_id: str,
        role: Role,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            metadata_json = json.dumps(metadata) if metadata else None
            self.conn.execute(
                """
                INSERT INTO messages (user_id, role, content, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, role, content, metadata_json),
            )
            self.trim_user_memory(user_id)

    def get_user_memory(
        self,
        user_id: str,
        limit: int | None = None,
    ) -> list[dict[str, str]]:
        lim = int(limit if limit is not None else self.max_memory)
        with self._lock:
            cursor = self.conn.execute(
                """
                SELECT role, content
                FROM messages
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, lim),
            )
            rows = cursor.fetchall()
        rows.reverse()
        return [{"role": r, "content": c} for r, c in rows]

    def trim_user_memory(
        self,
        user_id: str,
        max_rows: int | None = None,
    ) -> None:
        cap = int(max_rows if max_rows is not None else self.max_total_memory)
        with self._lock:
            self.conn.execute(
                """
                DELETE FROM messages
                WHERE user_id = ?
                  AND id NOT IN (
                      SELECT id
                      FROM messages
                      WHERE user_id = ?
                      ORDER BY id DESC
                      LIMIT ?
                  )
                """,
                (user_id, user_id, cap),
            )

    def forget_user(self, user_id: str) -> None:
        with self._lock:
            self.conn.execute(
                "DELETE FROM messages WHERE user_id = ?",
                (user_id,),
            )

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None


_async_store: AsyncMemoryStore | None = None
_sync_store: SyncMemoryStore | None = None


async def get_async_store() -> AsyncMemoryStore:
    global _async_store
    if _async_store is None:
        _async_store = AsyncMemoryStore(
            max_memory=MAX_MEMORY,
            max_total_memory=MAX_TOTAL_MEMORY,
        )
        await _async_store.initialize()
    return _async_store


def get_sync_store() -> SyncMemoryStore:
    global _sync_store
    if _sync_store is None:
        _sync_store = SyncMemoryStore(
            max_memory=MAX_MEMORY,
            max_total_memory=MAX_TOTAL_MEMORY,
        )
    return _sync_store


def store_message(user_id: str, role: Role, content: str) -> None:
    store = get_sync_store()
    store.store_message(user_id, role, content)


def get_user_memory(user_id: str, limit: int = MAX_MEMORY) -> list[dict[str, str]]:
    store = get_sync_store()
    return store.get_user_memory(user_id, limit)


def forget_user(user_id: str) -> None:
    store = get_sync_store()
    store.forget_user(user_id)


def trim_user_memory(user_id: str, max_rows: int = MAX_TOTAL_MEMORY) -> None:
    store = get_sync_store()
    store.trim_user_memory(user_id, max_rows)
