from __future__ import annotations

import asyncio
import os

from app.core.cache.backends.inmemory import InMemoryCache
from app.core.cache.backends.redis_backend import RedisCache
from app.core.cache.multi import MultiLevelCache

_lock = asyncio.Lock()
_instance: MultiLevelCache | None = None


async def get_cache() -> MultiLevelCache:
    global _instance
    if _instance is not None:
        return _instance
    async with _lock:
        if _instance is not None:
            return _instance
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        l1 = InMemoryCache(max_size=int(os.getenv("CACHE_L1_MAX", "20000")))
        l2 = RedisCache(url=redis_url, default_ttl=int(os.getenv("CACHE_TTL", "3600")))
        _instance = MultiLevelCache([l1, l2])
        return _instance
