from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

import asyncpg

from app.core.config import MAX_MEMORY, MAX_TOTAL_MEMORY
from app.core.logging import get_logger

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
        dsn: str | None = None,
        max_memory: int = MAX_MEMORY,
        max_total_memory: int = MAX_TOTAL_MEMORY,
        pool_min_size: int = 1,
        pool_max_size: int = 5,
    ):
        self.dsn = (
            dsn
            or os.getenv("MEMORY_DB_URL")
            or os.getenv("DATABASE_URL")
            or "postgresql://dev:dev@localhost:5432/devops_ai"
        )
        self.max_memory = int(max_memory)
        self.max_total_memory = int(max_total_memory)
        self.pool_min_size = int(pool_min_size)
        self.pool_max_size = int(pool_max_size)
        self._pool: asyncpg.Pool | None = None
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            self._pool = await asyncpg.create_pool(
                self.dsn, min_size=self.pool_min_size, max_size=self.pool_max_size
            )
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id BIGSERIAL PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        metadata JSONB,
                        timestamp TIMESTAMPTZ DEFAULT now(),
                        created_at TIMESTAMPTZ DEFAULT now()
                    );
                    CREATE INDEX IF NOT EXISTS idx_user_timestamp ON messages(user_id, timestamp DESC);
                    CREATE INDEX IF NOT EXISTS idx_user_created ON messages(user_id, created_at DESC);
                    """
                )
            self._initialized = True
            logger.info(f"initialized memory store pool_size={self.pool_max_size}")

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[asyncpg.Connection]:
        await self.initialize()
        assert self._pool is not None
        conn = await self._pool.acquire()
        try:
            yield conn
        finally:
            await self._pool.release(conn)

    async def store_message(
        self,
        user_id: str,
        role: MessageRole | str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if isinstance(role, str):
            role = MessageRole(role)
        async with self.get_connection() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO messages (user_id, role, content, metadata)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                user_id,
                role.value,
                content,
                metadata if metadata is not None else None,
            )
        message_id = int(row["id"])
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
            rows = await conn.fetch(
                """
                SELECT role, content, metadata, timestamp
                FROM messages
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id,
                lim,
            )
        rows = list(rows)[::-1]
        result: list[dict[str, Any]] = []
        for r in rows:
            item: dict[str, Any] = {"role": r["role"], "content": r["content"]}
            if include_metadata:
                item["metadata"] = r["metadata"] or {}
                item["timestamp"] = r["timestamp"]
            result.append(item)
        return result

    async def get_message_count(self, user_id: str) -> int:
        async with self.get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS c FROM messages WHERE user_id = $1", user_id
            )
        return int(row["c"] if row else 0)

    async def search_messages(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        async with self.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content, timestamp
                FROM messages
                WHERE user_id = $1 AND content ILIKE '%' || $2 || '%'
                ORDER BY created_at DESC
                LIMIT $3
                """,
                user_id,
                query,
                int(limit),
            )
        return [
            {"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]} for r in rows
        ]

    async def trim_user_memory(
        self,
        user_id: str,
        max_rows: int | None = None,
    ) -> int:
        cap = int(max_rows if max_rows is not None else self.max_total_memory)
        async with self.get_connection() as conn:
            result = await conn.execute(
                """
                DELETE FROM messages
                WHERE user_id = $1
                  AND id NOT IN (
                    SELECT id
                    FROM messages
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                  )
                """,
                user_id,
                cap,
            )
        deleted = int(result.split()[-1]) if result else 0
        if deleted > 0:
            logger.info(f"trimmed {deleted} messages for user_id={user_id}")
        return deleted

    async def forget_user(self, user_id: str) -> int:
        async with self.get_connection() as conn:
            result = await conn.execute("DELETE FROM messages WHERE user_id = $1", user_id)
        return int(result.split()[-1]) if result else 0

    async def get_statistics(self) -> dict[str, Any]:
        async with self.get_connection() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM messages")
            unique_users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM messages")
            role_rows = await conn.fetch("SELECT role, COUNT(*) FROM messages GROUP BY role")
            role_distribution = {r["role"]: r["count"] for r in role_rows}
            db_size = None
        return {
            "total_messages": int(total or 0),
            "unique_users": int(unique_users or 0),
            "role_distribution": role_distribution,
            "database_size_bytes": db_size,
            "pool_size": self.pool_max_size,
            "max_memory": self.max_memory,
            "max_total_memory": self.max_total_memory,
        }


_async_store: AsyncMemoryStore | None = None


async def get_async_store() -> AsyncMemoryStore:
    global _async_store
    if _async_store is None:
        _async_store = AsyncMemoryStore(
            max_memory=MAX_MEMORY,
            max_total_memory=MAX_TOTAL_MEMORY,
        )
        await _async_store.initialize()
    return _async_store
