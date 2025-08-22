from __future__ import annotations

from typing import Any, Awaitable, cast

import redis.asyncio as redis

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
        self._pool = redis.ConnectionPool.from_url(
            url,
            max_connections=max_connections,
            decode_responses=False,
        )
        self._client: redis.Redis | None = None

    async def _client_or_init(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis(connection_pool=self._pool)
            await self._client.ping()
        return self._client

    async def get(self, key: str) -> Any | None:
        cli = await self._client_or_init()
        raw = await cli.get(key)
        if raw is None:
            return None
        return loads(raw)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        cli = await self._client_or_init()
        data = dumps(value)
        seconds = ttl if ttl is not None else self.default_ttl
        if seconds > 0:
            return await cli.setex(key, seconds, data)
        fut = cast(Awaitable[bool], cli.set(key, data))
        return await fut

    async def delete(self, *keys: str) -> int:
        cli = await self._client_or_init()
        return await cli.delete(*keys)

    async def exists(self, *keys: str) -> int:
        cli = await self._client_or_init()
        return await cli.exists(*keys)

    async def expire(self, key: str, seconds: int) -> bool:
        cli = await self._client_or_init()
        return await cli.expire(key, seconds)

    async def incr(self, key: str, amount: int = 1) -> int:
        cli = await self._client_or_init()
        return await cli.incrby(key, amount)

    async def decr(self, key: str, amount: int = 1) -> int:
        cli = await self._client_or_init()
        return await cli.decrby(key, amount)

    async def hset(self, name: str, key: str, value: Any) -> int:
        cli = await self._client_or_init()
        return await cli.hset(name, key, dumps(value))

    async def hget(self, name: str, key: str) -> Any | None:
        cli = await self._client_or_init()
        raw = await cli.hget(name, key)
        if raw is None:
            return None
        return loads(raw)

    async def hgetall(self, name: str) -> dict[str, Any]:
        cli = await self._client_or_init()
        data = await cli.hgetall(name)
        out: dict[str, Any] = {}
        for k, v in data.items():
            out[k.decode() if isinstance(k, bytes) else str(k)] = loads(v)
        return out

    async def lpush(self, key: str, *values: Any) -> int:
        cli = await self._client_or_init()
        payload = [dumps(v) for v in values]
        fut = cast(Awaitable[int], cli.lpush(key, *payload))
        return await fut

    async def rpop(self, key: str, count: int | None = None) -> Any:
        cli = await self._client_or_init()
        if count is None:
            raw = await cli.rpop(key)
            return loads(raw) if raw is not None else None
        fut = cast(Awaitable[list[bytes] | None], cli.rpop(key, count))
        raw_list = await fut
        if raw_list is None:
            return None
        return [loads(b) for b in raw_list]

    async def invalidate(self, pattern: str | None = None) -> int:
        cli = await self._client_or_init()
        if pattern is None:
            keys = await cli.keys("*")
        else:
            keys = await cli.keys(pattern)
        if not keys:
            return 0
        return await cli.delete(*keys)

    async def aclose(self) -> None:
        if self._client:
            await self._client.close()
        await self._pool.disconnect()
