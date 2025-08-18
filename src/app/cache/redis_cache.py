from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Awaitable
from typing import Any, cast

import redis.asyncio as redis
from redis.asyncio import ConnectionPool


class CacheManager:
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        default_ttl: int = 3600,
        max_connections: int = 50,
    ):
        self.redis_url = redis_url
        self.default_ttl = default_ttl
        self.pool = ConnectionPool.from_url(
            redis_url,
            max_connections=max_connections,
            decode_responses=False,
        )
        self._client: redis.Redis | None = None

    async def initialize(self) -> None:
        self._client = redis.Redis(connection_pool=self.pool)
        await self._client.ping()

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            await self.pool.disconnect()

    async def _ensure_client(self) -> redis.Redis:
        if self._client is None:
            await self.initialize()
        client = self._client
        if client is None:
            raise RuntimeError("Redis client is not initialized")
        return client

    async def get(self, key: str, deserialize: bool = True) -> Any:
        client = await self._ensure_client()
        value = await client.get(key)
        if value is None:
            return None

        if not deserialize:
            return value

        if isinstance(value, bytes | bytearray | memoryview):
            raw = bytes(value).decode()
        else:
            raw = str(value)

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return raw

        if isinstance(data, dict) and data.get("__type__") == "bytes":
            b64_val = data.get("data")
            if not isinstance(b64_val, str | bytes | bytearray | memoryview):
                return b64_val
            try:
                return base64.b64decode(b64_val)
            except (binascii.Error, TypeError):
                return b64_val
        return data

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        serialize: bool = True,
    ) -> bool:
        client = await self._ensure_client()

        if serialize:
            if isinstance(value, bytes | bytearray | memoryview):
                b64 = base64.b64encode(bytes(value)).decode()
                value = json.dumps({"__type__": "bytes", "data": b64})
            else:
                try:
                    value = json.dumps(value)
                except (TypeError, ValueError) as exc:
                    raise TypeError("Unsupported value type") from exc

        if ttl is None:
            ttl = self.default_ttl

        if ttl > 0:
            return await client.setex(key, ttl, value)

        fut = cast(Awaitable[bool], client.set(key, value))
        return await fut

    async def delete(self, *keys: str) -> int:
        client = await self._ensure_client()
        return await client.delete(*keys)

    async def exists(self, *keys: str) -> int:
        client = await self._ensure_client()
        return await client.exists(*keys)

    async def expire(self, key: str, seconds: int) -> bool:
        client = await self._ensure_client()
        return await client.expire(key, seconds)

    async def incr(self, key: str, amount: int = 1) -> int:
        client = await self._ensure_client()
        return await client.incrby(key, amount)

    async def decr(self, key: str, amount: int = 1) -> int:
        client = await self._ensure_client()
        return await client.decrby(key, amount)

    async def lpush(self, key: str, *values: Any) -> int:
        client = await self._ensure_client()
        serialized: list[str] = []
        for v in values:
            if isinstance(v, str):
                serialized.append(v)
            elif isinstance(v, bytes | bytearray | memoryview):
                serialized.append(bytes(v).decode(errors="surrogatepass"))
            else:
                serialized.append(json.dumps(v))
        fut = cast(Awaitable[int], client.lpush(key, *serialized))
        return await fut

    async def rpop(self, key: str, count: int | None = None) -> Any:
        client = await self._ensure_client()
        fut = cast(
            Awaitable[bytes | list[bytes] | None],
            client.rpop(key, count),
        )
        result = await fut
        if result is None:
            return None

        if isinstance(result, list):
            out: list[Any] = []
            for item in result:
                try:
                    out.append(json.loads(item.decode()))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    out.append(item.decode())
            return out

        try:
            return json.loads(result.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return result.decode()

    async def hset(self, name: str, key: str, value: Any) -> int:
        client = await self._ensure_client()
        if isinstance(value, str):
            serialized = value
        elif isinstance(value, bytes | bytearray | memoryview):
            serialized = bytes(value).decode(errors="surrogatepass")
        else:
            serialized = json.dumps(value)
        fut = cast(Awaitable[int], client.hset(name, key, serialized))
        return await fut

    async def hget(self, name: str, key: str) -> Any:
        client = await self._ensure_client()
        fut = cast(Awaitable[bytes | None], client.hget(name, key))
        value = await fut
        if value is None:
            return None

        try:
            return json.loads(value.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return value.decode()

    async def hgetall(self, name: str) -> dict[str, Any]:
        client = await self._ensure_client()
        fut = cast(Awaitable[dict[bytes, bytes]], client.hgetall(name))
        data = await fut
        result: dict[str, Any] = {}
        for k, v in data.items():
            key = k.decode()
            try:
                result[key] = json.loads(v.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                result[key] = v.decode()
        return result
