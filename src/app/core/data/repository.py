from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Generic, TypeVar

import asyncpg
from opentelemetry import trace
from prometheus_client import Counter, Histogram
from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.observability.app_insights import app_insights

T = TypeVar("T", bound=BaseModel)

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)

DB_QUERIES = Counter(
    "db_queries_total",
    "Total database queries",
    labelnames=("op", "success"),
)

DB_LATENCY = Histogram(
    "db_query_duration_seconds",
    "Database query latency in seconds",
    labelnames=("op", "success"),
    buckets=(0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

REDIS_OPS = Counter(
    "redis_ops_total",
    "Total redis operations",
    labelnames=("op", "success"),
)

REDIS_LATENCY = Histogram(
    "redis_op_duration_seconds",
    "Redis operation latency in seconds",
    labelnames=("op", "success"),
    buckets=(0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)


class DataStore(ABC):
    @abstractmethod
    async def initialize(self) -> None: ...
    @abstractmethod
    async def close(self) -> None: ...


class PostgresStore(DataStore):
    def __init__(self, dsn: str) -> None:
        # Convert SQLAlchemy-style DSN to asyncpg-compatible format
        if dsn.startswith("postgresql+asyncpg://"):
            dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
        elif dsn.startswith("postgres+asyncpg://"):
            dsn = dsn.replace("postgres+asyncpg://", "postgres://")
        self.dsn = dsn
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        if self._pool is not None:
            return
        async with self._lock:
            if self._pool is not None:
                return
            min_size = max(1, settings.database.db_pool_size // 2)
            max_size = max(min_size, settings.database.db_pool_size)
            timeout = float(settings.database.db_pool_timeout)
            self._pool = await asyncpg.create_pool(
                self.dsn,
                min_size=min_size,
                max_size=max_size,
                max_inactive_connection_lifetime=float(settings.database.db_pool_recycle),
                command_timeout=timeout,
                init=self._init_connection,
            )
            logger.info("postgres pool initialized", dsn=self._safe_dsn())

    async def close(self) -> None:
        async with self._lock:
            pool = self._pool
            self._pool = None
            if pool is not None:
                await pool.close()
                logger.info("postgres pool closed")

    async def _init_connection(self, conn: asyncpg.Connection) -> None:
        app_name = settings.observability.otel_service_name or "devops-ai-api"
        await conn.execute("SET TIME ZONE 'UTC'")
        await conn.execute("SET statement_timeout = '30s'")
        await conn.execute("SET idle_in_transaction_session_timeout = '60s'")
        await conn.execute(f"SET application_name = '{app_name}'")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        pool = self._pool
        if pool is None:
            raise RuntimeError("postgres pool not initialized")
        async with pool.acquire() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        async with self.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def execute(self, query: str, *args: Any) -> str:
        return await self._run("execute", lambda c: c.execute(query, *args))

    async def executemany(self, query: str, args_iter: list[tuple[Any, ...]]) -> None:
        async def _fn(c: asyncpg.Connection) -> None:
            await c.executemany(query, args_iter)

        await self._run("executemany", _fn)

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        return await self._run("fetch", lambda c: c.fetch(query, *args))

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        return await self._run("fetchrow", lambda c: c.fetchrow(query, *args))

    async def fetchval(self, query: str, *args: Any) -> Any:
        return await self._run("fetchval", lambda c: c.fetchval(query, *args))

    async def _run(self, op: str, fn: Any) -> Any:
        start = time.perf_counter()
        success = "false"
        with tracer.start_as_current_span(f"db.{op}") as span:
            span.set_attribute("db.system", "postgresql")
            span.set_attribute("db.operation", op)
            try:
                async with self.acquire() as conn:
                    res = await fn(conn)
                success = "true"
                return res
            except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError) as exc:
                app_insights.track_exception(exc)
                logger.warning("db transient error, retrying", op=op)
                async with self.transaction() as conn:
                    res = await fn(conn)
                success = "true"
                return res
            except Exception as exc:
                app_insights.track_exception(exc)
                span.record_exception(exc)
                logger.error("db operation failed", op=op, error=str(exc))
                raise
            finally:
                elapsed = time.perf_counter() - start
                DB_QUERIES.labels(op=op, success=success).inc()
                DB_LATENCY.labels(op=op, success=success).observe(elapsed)
                if settings.database.enable_query_logging:
                    ms = round(elapsed * 1000, 2)
                    level = "warning" if ms >= settings.database.slow_query_threshold_ms else "info"
                    log = getattr(logger, level)
                    log("db operation", op=op, duration_ms=ms)

    def _safe_dsn(self) -> str:
        s = str(self.dsn)
        if "@" in s:
            left, right = s.split("@", 1)
            if "://" in left:
                scheme, auth = left.split("://", 1)
                auth_safe = auth.split(":", 1)[0]
                return f"{scheme}://{auth_safe}:***@{right}"
        return s


class RedisStore(DataStore):
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._client: Redis | None = None

    async def initialize(self) -> None:
        if self._client is not None:
            return
        self._client = Redis.from_url(
            self.dsn,
            decode_responses=False,
            max_connections=int(settings.database.redis_max_connections),
            socket_timeout=float(settings.database.redis_socket_timeout),
        )
        logger.info("redis client initialized")

    async def close(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            await client.aclose()
            logger.info("redis client closed")

    async def get(self, key: str) -> Any:
        return await self._redis_op("get", lambda c: c.get(key))

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        import orjson

        data = orjson.dumps(value)
        to_ttl = ttl if ttl is not None else int(settings.cache.default_ttl_seconds)
        await self._redis_op("setex", lambda c: c.setex(key, to_ttl, data))

    async def delete(self, key: str) -> None:
        await self._redis_op("delete", lambda c: c.delete(key))

    async def _redis_op(self, op: str, fn: Any) -> Any:
        start = time.perf_counter()
        success = "false"
        with tracer.start_as_current_span(f"redis.{op}") as span:
            try:
                if not self._client:
                    return None
                res = await fn(self._client)
                success = "true"
                if op == "get" and res is not None:
                    import orjson

                    return orjson.loads(res)
                return res
            except Exception as exc:
                app_insights.track_exception(exc)
                span.record_exception(exc)
                logger.error("redis operation failed", op=op, error=str(exc))
                raise
            finally:
                elapsed = time.perf_counter() - start
                REDIS_OPS.labels(op=op, success=success).inc()
                REDIS_LATENCY.labels(op=op, success=success).observe(elapsed)


class UnifiedDataLayer:
    def __init__(self) -> None:
        self._postgres: PostgresStore | None = None
        self._redis: RedisStore | None = None
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            if settings.database.postgres_dsn:
                self._postgres = PostgresStore(str(settings.database.postgres_dsn))
                await self._postgres.initialize()
            if settings.database.redis_dsn:
                self._redis = RedisStore(str(settings.database.redis_dsn))
                await self._redis.initialize()
            self._initialized = True
            logger.info("unified data layer initialized")

    async def close(self) -> None:
        async with self._lock:
            if self._redis:
                await self._redis.close()
                self._redis = None
            if self._postgres:
                await self._postgres.close()
                self._postgres = None
            self._initialized = False
            logger.info("unified data layer closed")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        if not self._postgres:
            raise RuntimeError("postgres not configured")
        async with self._postgres.transaction() as tx:
            yield tx

    async def cache_get(self, key: str) -> Any:
        if self._redis:
            return await self._redis.get(key)
        return None

    async def cache_set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if self._redis:
            await self._redis.set(key, value, ttl)

    async def cache_delete(self, key: str) -> None:
        if self._redis:
            await self._redis.delete(key)
    
    # Delegation methods for AsyncMemoryStore compatibility
    async def execute(self, query: str, *args: Any) -> str:
        if not self._postgres:
            raise RuntimeError("postgres not configured")
        return await self._postgres.execute(query, *args)
    
    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        if not self._postgres:
            raise RuntimeError("postgres not configured") 
        return await self._postgres.fetch(query, *args)
    
    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        if not self._postgres:
            raise RuntimeError("postgres not configured")
        return await self._postgres.fetchrow(query, *args)
    
    async def fetchval(self, query: str, *args: Any) -> Any:
        if not self._postgres:
            raise RuntimeError("postgres not configured")
        return await self._postgres.fetchval(query, *args)
    
    @asynccontextmanager
    async def connection(self) -> AsyncIterator[asyncpg.Connection]:
        # Alias for transaction for backward compatibility
        async with self.transaction() as conn:
            yield conn

    @property
    def pg(self) -> PostgresStore:
        if not self._postgres:
            raise RuntimeError("postgres not configured")
        return self._postgres


_DATA_LAYER: UnifiedDataLayer | None = None


def get_data_layer() -> UnifiedDataLayer:
    global _DATA_LAYER
    if _DATA_LAYER is None:
        _DATA_LAYER = UnifiedDataLayer()
    return _DATA_LAYER


class Repository(Generic[T], ABC):
    def __init__(
        self, data_layer: UnifiedDataLayer, model_class: type[T], table_name: str | None = None
    ) -> None:
        self.data = data_layer
        self.model_class = model_class
        self.table_name = table_name or f"{model_class.__name__.lower()}s"

    @abstractmethod
    def serialize(self, model: T) -> dict[str, Any]: ...

    def _cache_key(self, id: str) -> str:
        env = settings.environment
        return f"{env}:{self.table_name}:{id}"

    async def get(self, id: str) -> T | None:
        ck = self._cache_key(id)
        cached = await self.data.cache_get(ck)
        if cached:
            return self.model_class(**cached)
        async with self.data.transaction() as conn:
            row = await conn.fetchrow(f"SELECT * FROM {self.table_name} WHERE id = $1", id)
            if not row:
                return None
            model = self.model_class(**dict(row))
            await self.data.cache_set(ck, model.model_dump())
            return model

    async def delete(self, id: str) -> bool:
        async with self.data.transaction() as conn:
            res = await conn.execute(f"DELETE FROM {self.table_name} WHERE id = $1", id)
        await self.data.cache_delete(self._cache_key(id))
        return res.upper().startswith("DELETE")

    async def list(self, limit: int = 100, offset: int = 0) -> list[T]:
        async with self.data.transaction() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM {self.table_name} ORDER BY id DESC LIMIT $1 OFFSET $2",
                limit,
                offset,
            )
            return [self.model_class(**dict(r)) for r in rows]

    async def upsert(self, model: T) -> T:
        data = self.serialize(model)
        if not data.get("id"):
            data["id"] = str(uuid.uuid4())
        columns = list(data.keys())
        values = list(data.values())
        placeholders = ", ".join(f"${i}" for i in range(1, len(values) + 1))
        cols_csv = ", ".join(columns)
        set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in columns if c not in {"id"})
        sql = (
            f"INSERT INTO {self.table_name} ({cols_csv}) VALUES ({placeholders}) "
            f"ON CONFLICT (id) DO UPDATE SET {set_clause} RETURNING *"
        )
        async with self.data.transaction() as conn:
            row = await conn.fetchrow(sql, *values)
        out = self.model_class(**dict(row))
        await self.data.cache_set(
            self._cache_key(out.model_dump().get("id", data["id"])), out.model_dump()
        )
        return out

    async def touch(self, id: str) -> None:
        now = datetime.utcnow()
        async with self.data.transaction() as conn:
            try:
                await conn.execute(
                    f"UPDATE {self.table_name} SET updated_at = $2 WHERE id = $1",
                    id,
                    now,
                )
            except Exception as exc:
                app_insights.track_exception(exc)
                logger.warning("touch failed", table=self.table_name, id=id)
