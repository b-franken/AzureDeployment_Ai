from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from app.core.config import MAX_MEMORY, MAX_TOTAL_MEMORY
from app.core.database import get_db
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
        max_memory: int = MAX_MEMORY,
        max_total_memory: int = MAX_TOTAL_MEMORY,
    ):
        self.max_memory = int(max_memory)
        self.max_total_memory = int(max_total_memory)
        self.db = get_db()
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await self.db.initialize()
            await self.db.execute(
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

                CREATE INDEX IF NOT EXISTS idx_user_timestamp
                    ON messages (user_id, timestamp DESC);

                CREATE INDEX IF NOT EXISTS idx_user_created
                    ON messages (user_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_user_thread_created
                    ON messages (
                        user_id,
                        (metadata->>'thread_id'),
                        created_at DESC
                    );

                CREATE INDEX IF NOT EXISTS idx_user_agent_created
                    ON messages (
                        user_id,
                        (metadata->>'agent'),
                        created_at DESC
                    );

                CREATE INDEX IF NOT EXISTS idx_messages_metadata_gin
                    ON messages USING GIN (metadata);
                """
            )
            self._initialized = True
            logger.info("initialized memory store")

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[Any]:
        await self.initialize()
        async with self.db.connection() as conn:
            yield conn

    async def store_message(
        self,
        user_id: str,
        role: MessageRole | str,
        content: str,
        metadata: dict[str, Any] | None = None,
        *,
        thread_id: str | None = None,
        agent: str | None = None,
    ) -> int:
        if isinstance(role, str):
            role = MessageRole(role)
        merged = dict(metadata or {})
        if thread_id is not None:
            merged["thread_id"] = thread_id
        if agent is not None:
            merged["agent"] = agent
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
                merged if merged else None,
            )
        message_id = int(row["id"])
        await self.trim_user_memory(user_id)
        logger.debug("stored message id=%s user_id=%s", message_id, user_id)
        return message_id

    async def get_user_memory(
        self,
        user_id: str,
        limit: int | None = None,
        include_metadata: bool = False,
        *,
        thread_id: str | None = None,
        agent: str | None = None,
    ) -> list[dict[str, Any]]:
        lim = int(limit if limit is not None else self.max_memory)
        conditions: list[str] = ["user_id = $1"]
        params: list[Any] = [user_id]
        idx = 2
        if thread_id is not None:
            conditions.append(f"metadata->>'thread_id' = ${idx}")
            params.append(thread_id)
            idx += 1
        if agent is not None:
            conditions.append(f"metadata->>'agent' = ${idx}")
            params.append(agent)
            idx += 1
        where_sql = " AND ".join(conditions)
        query = f"""
            SELECT role, content, metadata, timestamp
            FROM messages
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT ${idx}
        """
        params.append(lim)
        async with self.get_connection() as conn:
            rows = await conn.fetch(query, *params)
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
        *,
        thread_id: str | None = None,
        agent: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = ["user_id = $1"]
        params: list[Any] = [user_id]
        idx = 2
        if thread_id is not None:
            conditions.append(f"metadata->>'thread_id' = ${idx}")
            params.append(thread_id)
            idx += 1
        if agent is not None:
            conditions.append(f"metadata->>'agent' = ${idx}")
            params.append(agent)
            idx += 1
        conditions.append(f"content ILIKE '%%' || ${idx} || '%%'")
        params.append(query)
        idx += 1
        where_sql = " AND ".join(conditions)
        sql = f"""
            SELECT role, content, timestamp
            FROM messages
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT ${idx}
        """
        params.append(int(limit))
        async with self.get_connection() as conn:
            rows = await conn.fetch(sql, *params)
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
            logger.info("trimmed %s messages for user_id=%s", deleted, user_id)
        return deleted

    async def forget_user(self, user_id: str) -> int:
        async with self.get_connection() as conn:
            result = await conn.execute("DELETE FROM messages WHERE user_id = $1", user_id)
        return int(result.split()[-1]) if result else 0

    async def get_statistics(self) -> dict[str, Any]:
        async with self.get_connection() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM messages")
            unique_users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM messages")
            role_rows = await conn.fetch("SELECT role, COUNT(*) AS cnt FROM messages GROUP BY role")
            role_distribution = {r["role"]: r["cnt"] for r in role_rows}
        return {
            "total_messages": int(total or 0),
            "unique_users": int(unique_users or 0),
            "role_distribution": role_distribution,
            "database_size_bytes": None,
            "pool_size": None,
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
