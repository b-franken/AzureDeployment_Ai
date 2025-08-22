from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.logging import get_logger
from app.database.connection import DatabasePool

logger = get_logger(__name__)


class DatabaseManager:
    def __init__(
        self,
        dsn: str | None = None,
        min_size: int = 5,
        max_size: int = 50,
    ) -> None:
        self.dsn = (
            dsn or os.getenv("DATABASE_URL") or "postgresql://dev:dev@localhost:5432/devops_ai"
        )
        self.pool = DatabasePool(self.dsn, min_size=min_size, max_size=max_size)
        self._init_lock = asyncio.Lock()
        self._ready = False

    async def initialize(self) -> None:
        if self._ready:
            return
        async with self._init_lock:
            if self._ready:
                return
            await self.pool.initialize()
            self._ready = True
            logger.info("database manager initialized")

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[Any]:
        async with self.pool.acquire() as conn:
            yield conn

    async def execute(self, query: str, *args: Any) -> str:
        return await self.pool.execute(query, *args)

    async def executemany(self, query: str, args_iter: list[tuple[Any, ...]]) -> None:
        await self.pool.executemany(query, args_iter)

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        return await self.pool.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Any | None:
        return await self.pool.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        return await self.pool.fetchval(query, *args)

    async def close(self) -> None:
        await self.pool.close()


_db: DatabaseManager | None = None


def get_db() -> DatabaseManager:
    global _db
    if _db is None:
        _db = DatabaseManager()
    return _db
