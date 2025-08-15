from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from asyncpg import Connection, Pool, Record


class DatabasePool:
    def __init__(
        self,
        dsn: str,
        min_size: int = 10,
        max_size: int = 100,
        max_queries: int = 50000,
        max_inactive_connection_lifetime: float = 300.0,
    ):
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self.max_queries = max_queries
        self.max_inactive_connection_lifetime = max_inactive_connection_lifetime
        self._pool: Pool | None = None
        self._lock: asyncio.Lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._lock:
            if self._pool is None:
                self._pool = await asyncpg.create_pool(
                    self.dsn,
                    min_size=self.min_size,
                    max_size=self.max_size,
                    max_queries=self.max_queries,
                    max_inactive_connection_lifetime=(self.max_inactive_connection_lifetime),
                    command_timeout=60,
                )

    async def close(self) -> None:
        async with self._lock:
            pool = self._pool
            if pool is not None:
                await pool.close()
                self._pool = None

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[Connection, None]:
        pool = self._pool
        if pool is None:
            await self.initialize()
            pool = self._pool
        assert pool is not None
        async with pool.acquire() as connection:
            yield connection

    async def execute(self, query: str, *args: Any) -> str:
        async with self.acquire() as connection:
            return await connection.execute(query, *args)

    async def fetch(self, query: str, *args: Any) -> list[Record]:
        async with self.acquire() as connection:
            return await connection.fetch(query, *args)

    async def fetchrow(
        self,
        query: str,
        *args: Any,
    ) -> Record | None:
        async with self.acquire() as connection:
            return await connection.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        async with self.acquire() as connection:
            return await connection.fetchval(query, *args)
