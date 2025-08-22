from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any

from app.core.cache.base import CacheBackend


class InMemoryCache(CacheBackend):
    def __init__(self, max_size: int = 10000, default_ttl: int = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._data: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, expiry = item
            if expiry and expiry < time.time():
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        async with self._lock:
            seconds = ttl if ttl is not None else self.default_ttl
            expiry = time.time() + seconds if seconds > 0 else 0.0
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (value, expiry)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)
            return True

    async def delete(self, *keys: str) -> int:
        async with self._lock:
            count = 0
            for k in keys:
                if k in self._data:
                    del self._data[k]
                    count += 1
            return count

    async def exists(self, *keys: str) -> int:
        async with self._lock:
            return sum(1 for k in keys if k in self._data)

    async def expire(self, key: str, seconds: int) -> bool:
        async with self._lock:
            item = self._data.get(key)
            if item is None:
                return False
            value, _ = item
            expiry = time.time() + seconds if seconds > 0 else 0.0
            self._data[key] = (value, expiry)
            return True

    async def incr(self, key: str, amount: int = 1) -> int:
        async with self._lock:
            current = await self.get(key)
            v = int(current or 0) + amount
            await self.set(key, v, ttl=self.default_ttl)
            return v

    async def decr(self, key: str, amount: int = 1) -> int:
        return await self.incr(key, -amount)

    async def hset(self, name: str, key: str, value: Any) -> int:
        async with self._lock:
            mapping = await self.get(name) or {}
            mapping[str(key)] = value
            await self.set(name, mapping, ttl=self.default_ttl)
            return 1

    async def hget(self, name: str, key: str) -> Any | None:
        mapping = await self.get(name) or {}
        return mapping.get(str(key))

    async def hgetall(self, name: str) -> dict[str, Any]:
        return dict(await self.get(name) or {})

    async def lpush(self, key: str, *values: Any) -> int:
        async with self._lock:
            lst = await self.get(key) or []
            lst = list(values) + list(lst)
            await self.set(key, lst, ttl=self.default_ttl)
            return len(lst)

    async def rpop(self, key: str, count: int | None = None) -> Any:
        async with self._lock:
            lst = await self.get(key) or []
            if not lst:
                return None
            if count is None:
                return lst.pop() if lst else None
            out = []
            for _ in range(min(count, len(lst))):
                out.append(lst.pop())
            await self.set(key, lst, ttl=self.default_ttl)
            return out

    async def invalidate(self, pattern: str | None = None) -> int:
        async with self._lock:
            if pattern is None:
                n = len(self._data)
                self._data.clear()
                return n
            keys = [k for k in self._data if pattern in k]
            for k in keys:
                del self._data[k]
            return len(keys)

    async def aclose(self) -> None:
        return None
