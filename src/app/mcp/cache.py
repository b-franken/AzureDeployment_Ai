from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any


class MCPCache:
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            if key not in self._cache:
                return None

            value, expiry = self._cache[key]
            if time.time() > expiry:
                del self._cache[key]
                return None

            self._cache.move_to_end(key)
            return value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        async with self._lock:
            ttl = ttl or self.default_ttl
            expiry = time.time() + ttl

            if key in self._cache:
                self._cache.move_to_end(key)

            self._cache[key] = (value, expiry)

            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    async def invalidate(self, pattern: str | None = None) -> int:
        async with self._lock:
            if pattern is None:
                count = len(self._cache)
                self._cache.clear()
                return count

            keys_to_delete = [k for k in self._cache.keys() if pattern in k]

            for key in keys_to_delete:
                del self._cache[key]

            return len(keys_to_delete)

    async def cleanup(self) -> int:
        async with self._lock:
            now = time.time()
            expired_keys = [k for k, (_, expiry) in self._cache.items() if now > expiry]

            for key in expired_keys:
                del self._cache[key]

            return len(expired_keys)
