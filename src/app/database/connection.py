# src/app/database/connection.py
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from asyncpg import Connection, Pool, Record

logger = logging.getLogger(__name__)


class DatabasePool:
    def __init__(
        self,
        dsn: str,
        min_size: int = 10,
        max_size: int = 100,
        max_queries: int = 50000,
        max_inactive_connection_lifetime: float = 300.0,
        command_timeout: float = 60.0,
        health_check_interval: float = 30.0,
        validation_query: str = "SELECT 1",
        validation_timeout: float = 3.0,
        health_failure_threshold: int = 3,
    ):
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self.max_queries = max_queries
        self.max_inactive_connection_lifetime = max_inactive_connection_lifetime
        self.command_timeout = command_timeout
        self.health_check_interval = health_check_interval
        self.validation_query = validation_query
        self.validation_timeout = validation_timeout
        self.health_failure_threshold = health_failure_threshold
        self._pool: Pool | None = None
        self._lock = asyncio.Lock()
        self._health_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    @property
    def is_initialized(self) -> bool:
        return self._pool is not None

    async def initialize(self) -> None:
        async with self._lock:
            if self._pool is None:
                self._pool = await asyncpg.create_pool(
                    self.dsn,
                    min_size=self.min_size,
                    max_size=self.max_size,
                    max_queries=self.max_queries,
                    max_inactive_connection_lifetime=self.max_inactive_connection_lifetime,
                    command_timeout=self.command_timeout,
                    init=self._init_connection,
                )
                self._stop_event.clear()
                self._health_task = asyncio.create_task(
                    self._health_check_loop(), name="db-health-check"
                )

    async def close(self) -> None:
        async with self._lock:
            self._stop_event.set()
            task = self._health_task
            self._health_task = None
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            pool = self._pool
            self._pool = None
            if pool is not None:
                await pool.close()

    async def _restart_pool(self) -> None:
        async with self._lock:
            pool = self._pool
            if pool is not None:
                await pool.close()
            self._pool = await asyncpg.create_pool(
                self.dsn,
                min_size=self.min_size,
                max_size=self.max_size,
                max_queries=self.max_queries,
                max_inactive_connection_lifetime=self.max_inactive_connection_lifetime,
                command_timeout=self.command_timeout,
                init=self._init_connection,
            )

    async def _init_connection(self, conn: Connection) -> None:
        app_name = os.getenv("APP_NAME") or "app"
        await conn.execute("SET TIME ZONE 'UTC'")
        await conn.execute("SET statement_timeout = '30s'")
        await conn.execute("SET idle_in_transaction_session_timeout = '60s'")
        await conn.execute(f"SET application_name = '{app_name}'")

    async def _validate(self, conn: Connection) -> bool:
        if conn.is_closed():
            return False
        try:
            await asyncio.wait_for(
                conn.fetchval(self.validation_query), timeout=self.validation_timeout
            )
            return True
        except Exception as exc:
            logger.warning("Connection validation failed: %s", exc)
            try:
                conn.terminate()
            except Exception as exc:
                logger.debug("Failed to terminate connection: %s", exc)
            return False

    async def _health_check_loop(self) -> None:
        failures = 0
        try:
            while not self._stop_event.is_set():
                jitter = random.uniform(0, self.health_check_interval * 0.2)
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.health_check_interval + jitter
                )
                if self._stop_event.is_set():
                    break
                try:
                    await self.fetchval(self.validation_query)
                    failures = 0
                except Exception as exc:
                    failures += 1
                    logger.error(
                        "Database health check failed (%s/%s): %s",
                        failures,
                        self.health_failure_threshold,
                        exc,
                    )
                    if failures >= self.health_failure_threshold:
                        logger.warning(
                            "Restarting database pool after consecutive health check failures"
                        )
                        await self._restart_pool()
                        failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Health check loop crashed: %s", exc)

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[Connection, None]:
        pool = self._pool
        if pool is None:
            
            pool = self._pool
        if pool is None:
            raise RuntimeError("Database pool is not initialized")
        async with pool.acquire() as connection:
            is_valid = await self._validate(connection)
            if not is_valid:
                raise ConnectionError("Failed to validate database connection from pool")
            yield connection

    async def execute(self, query: str, *args: Any) -> str:
        try:
            async with self.acquire() as connection:
                return await connection.execute(query, *args)
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError):
            await self._restart_pool()
            async with self.acquire() as connection:
                return await connection.execute(query, *args)

    async def executemany(self, query: str, args_iter: list[tuple[Any, ...]]) -> None:
        try:
            async with self.acquire() as connection:
                await connection.executemany(query, args_iter)
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError):
            await self._restart_pool()
            async with self.acquire() as connection:
                await connection.executemany(query, args_iter)

    async def fetch(self, query: str, *args: Any) -> list[Record]:
        try:
            async with self.acquire() as connection:
                return await connection.fetch(query, *args)
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError):
            await self._restart_pool()
            async with self.acquire() as connection:
                return await connection.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Record | None:
        try:
            async with self.acquire() as connection:
                return await connection.fetchrow(query, *args)
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError):
            await self._restart_pool()
            async with self.acquire() as connection:
                return await connection.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        try:
            async with self.acquire() as connection:
                return await connection.fetchval(query, *args)
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError):
            await self._restart_pool()
            async with self.acquire() as connection:
                return await connection.fetchval(query, *args)
