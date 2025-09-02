from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, cast

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from app.core.cache.base import CacheBackend
from app.core.cache.serializers import dumps, loads


class RedisCache(CacheBackend):
    def __init__(
        self,
        url: str,
        default_ttl: int = 3600,
        max_connections: int = 100,
    ):
        self.default_ttl = default_ttl
        self._pool = ConnectionPool.from_url(
            url,
            max_connections=max_connections,
            decode_responses=True,
        )
        self._client: Redis | None = None

    async def _client_or_init(self) -> Redis:
        if self._client is None:
            self._client = Redis(connection_pool=self._pool)
            fut = cast("Awaitable[bool]", self._client.ping())
            await fut
        return self._client

    async def get(self, key: str) -> Any | None:
        try:
            cli = await self._client_or_init()
            fut = cast("Awaitable[str | None]", cli.get(key))
            raw = await fut
            if raw is None:
                return None
            return loads(raw.encode("utf-8"))
        except RedisError:
            raise

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        try:
            cli = await self._client_or_init()
            data = dumps(value).decode("utf-8")
            seconds = ttl if ttl is not None else self.default_ttl
            if seconds > 0:
                fut = cast("Awaitable[bool]", cli.setex(key, seconds, data))
                return await fut
            fut = cast("Awaitable[bool]", cli.set(key, data))
            return await fut
        except RedisError:
            raise

    async def delete(self, *keys: str) -> int:
        try:
            cli = await self._client_or_init()
            fut = cast("Awaitable[int]", cli.delete(*keys))
            return await fut
        except RedisError:
            raise

    async def exists(self, *keys: str) -> int:
        try:
            cli = await self._client_or_init()
            fut = cast("Awaitable[int]", cli.exists(*keys))
            return await fut
        except RedisError:
            raise

    async def expire(self, key: str, seconds: int) -> bool:
        try:
            cli = await self._client_or_init()
            fut = cast("Awaitable[bool]", cli.expire(key, seconds))
            return await fut
        except RedisError:
            raise

    async def incr(self, key: str, amount: int = 1) -> int:
        try:
            cli = await self._client_or_init()
            fut = cast("Awaitable[int]", cli.incrby(key, amount))
            return await fut
        except RedisError:
            raise

    async def decr(self, key: str, amount: int = 1) -> int:
        try:
            cli = await self._client_or_init()
            fut = cast("Awaitable[int]", cli.decrby(key, amount))
            return await fut
        except RedisError:
            raise

    async def hset(self, name: str, key: str, value: Any) -> int:
        try:
            cli = await self._client_or_init()
            serialized_value = dumps(value).decode("utf-8")
            fut = cast("Awaitable[int]", cli.hset(name, key, serialized_value))
            return await fut
        except RedisError:
            raise

    async def hget(self, name: str, key: str) -> Any | None:
        try:
            cli = await self._client_or_init()
            fut = cast("Awaitable[str | None]", cli.hget(name, key))
            raw = await fut
            if raw is None:
                return None
            return loads(raw.encode("utf-8"))
        except RedisError:
            raise

    async def hgetall(self, name: str) -> dict[str, Any]:
        try:
            cli = await self._client_or_init()
            fut = cast("Awaitable[dict[bytes, bytes]]", cli.hgetall(name))
            data = await fut
            out: dict[str, Any] = {}
            for k, v in data.items():
                out[(k.decode() if isinstance(k, bytes) else str(k))] = loads(v)
            return out
        except RedisError:
            raise

    async def lpush(self, key: str, *values: Any) -> int:
        try:
            cli = await self._client_or_init()
            payload = [dumps(v) for v in values]
            fut = cast("Awaitable[int]", cli.lpush(key, *payload))
            return await fut
        except RedisError:
            raise

    async def rpop(self, key: str, count: int | None = None) -> Any:
        try:
            cli = await self._client_or_init()
            if count is None:
                fut_one = cast("Awaitable[bytes | None]", cli.rpop(key))
                raw = await fut_one
                return loads(raw) if raw is not None else None
            fut_many = cast("Awaitable[list[bytes] | None]", cli.rpop(key, count))
            raw_list = await fut_many
            if raw_list is None:
                return None
            return [loads(b) for b in raw_list]
        except RedisError:
            raise

    async def invalidate(self, pattern: str | None = None) -> int:
        try:
            cli = await self._client_or_init()
            if pattern is None:
                fut_keys = cast("Awaitable[list[bytes]]", cli.keys("*"))
                keys = await fut_keys
            else:
                fut_keys = cast("Awaitable[list[bytes]]", cli.keys(pattern))
                keys = await fut_keys
            if not keys:
                return 0
            fut_del = cast("Awaitable[int]", cli.delete(*keys))
            return await fut_del
        except RedisError:
            raise

    async def aclose(self) -> None:
        if self._client:
            fut = cast("Awaitable[bool]", self._client.close())
            await fut
        fut_pool = cast("Awaitable[None]", self._pool.disconnect())
        await fut_pool
