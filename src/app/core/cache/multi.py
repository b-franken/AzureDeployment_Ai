from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from app.core.cache.base import CacheBackend


class MultiLevelCache:
    def __init__(self, levels: Sequence[CacheBackend]):
        if not levels:
            raise ValueError("levels required")
        self.levels = list(levels)

    async def get(self, key: str) -> Any | None:
        value = None
        hit_index = -1
        for i, lvl in enumerate(self.levels):
            value = await lvl.get(key)
            if value is not None:
                hit_index = i
                break
        if value is None:
            return None
        if hit_index > 0:
            async with asyncio.TaskGroup() as tg:
                for j in range(hit_index):
                    tg.create_task(self.levels[j].set(key, value))
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        async with asyncio.TaskGroup() as tg:
            for lvl in self.levels:
                tg.create_task(lvl.set(key, value, ttl))
        return True

    async def delete(self, *keys: str) -> int:
        deleted = 0
        async with asyncio.TaskGroup() as tg:
            for lvl in self.levels:
                tg.create_task(lvl.delete(*keys))
        for lvl in self.levels:
            deleted += await lvl.exists(*keys)
        return deleted

    async def exists(self, *keys: str) -> int:
        total = 0
        for lvl in self.levels:
            total += await lvl.exists(*keys)
        return 1 if total > 0 else 0

    async def expire(self, key: str, seconds: int) -> bool:
        ok = False
        async with asyncio.TaskGroup() as tg:
            for lvl in self.levels:
                tg.create_task(lvl.expire(key, seconds))
        for lvl in self.levels:
            ok |= await lvl.exists(key) > 0
        return ok

    async def incr(self, key: str, amount: int = 1) -> int:
        value = 0
        for lvl in reversed(self.levels):
            value = await lvl.incr(key, amount)
            if value:
                break
        async with asyncio.TaskGroup() as tg:
            for lvl in self.levels:
                tg.create_task(lvl.set(key, value))
        return value

    async def decr(self, key: str, amount: int = 1) -> int:
        return await self.incr(key, -amount)

    async def hset(self, name: str, key: str, value: Any) -> int:
        async with asyncio.TaskGroup() as tg:
            for lvl in self.levels:
                tg.create_task(lvl.hset(name, key, value))
        return 1

    async def hget(self, name: str, key: str) -> Any | None:
        value = None
        hit_index = -1
        for i, lvl in enumerate(self.levels):
            value = await lvl.hget(name, key)
            if value is not None:
                hit_index = i
                break
        if value is None:
            return None
        if hit_index > 0:
            async with asyncio.TaskGroup() as tg:
                for j in range(hit_index):
                    tg.create_task(self.levels[j].hset(name, key, value))
        return value

    async def hgetall(self, name: str) -> dict[str, Any]:
        data = await self.levels[0].hgetall(name)
        if data:
            return data
        for i in range(1, len(self.levels)):
            data = await self.levels[i].hgetall(name)
            if data:
                async with asyncio.TaskGroup() as tg:
                    for j in range(i):
                        tg.create_task(self.levels[j].set(name, data))
                return data
        return {}

    async def lpush(self, key: str, *values: Any) -> int:
        n = 0
        async with asyncio.TaskGroup() as tg:
            for lvl in self.levels:
                tg.create_task(lvl.lpush(key, *values))
        for lvl in self.levels:
            n = await lvl.exists(key)
            if n:
                break
        return n

    async def rpop(self, key: str, count: int | None = None) -> Any:
        value = await self.levels[0].rpop(key, count)
        if value is not None:
            async with asyncio.TaskGroup() as tg:
                for i in range(1, len(self.levels)):
                    tg.create_task(self.levels[i].set(key, await self.levels[0].get(key)))
        return value

    async def invalidate(self, pattern: str | None = None) -> int:
        async with asyncio.TaskGroup() as tg:
            for lvl in self.levels:
                tg.create_task(lvl.invalidate(pattern))
        return 0

    async def aclose(self) -> None:
        async with asyncio.TaskGroup() as tg:
            for lvl in self.levels:
                tg.create_task(lvl.aclose())
