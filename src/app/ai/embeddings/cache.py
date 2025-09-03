from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

from app.core.logging import get_logger

try:
    from redis.asyncio import Redis
except Exception:  # noqa: BLE001
    Redis = None  # type: ignore[assignment,misc]

logger = get_logger(__name__)


_normalize_re = re.compile(r"\s+")


def normalize_query(text: str) -> str:
    """Normalize query text to improve cache hit rates."""
    normalized = text.lower().strip()
    normalized = _normalize_re.sub(" ", normalized)
    normalized = re.sub(r"[.,!?;:]", "", normalized)
    return normalized


def normkey(text: str) -> str:

    normalized = normalize_query(text)
    return hashlib.blake2b(normalized.encode("utf-8"), digest_size=16).hexdigest()


class RedisCache:
    def __init__(self, url: str, ttl_seconds: int) -> None:
        if Redis is None:
            logger.error("Redis client not available, cannot initialize cache")
            raise RuntimeError("redis missing")
        logger.info("Initializing Redis cache", url=url, ttl_seconds=ttl_seconds)
        self._r = Redis.from_url(url, decode_responses=False)
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    async def get_many(self, keys: list[str]) -> dict[str, list[float]]:
        if not keys:
            return {}
        logger.debug("Retrieving cached embeddings", key_count=len(keys))
        async with self._lock:
            vals = await self._r.mget(keys)
        out: dict[str, list[float]] = {}
        cache_hits = 0
        for k, v in zip(keys, vals, strict=False):
            if v is None:
                continue
            try:
                out[k] = json.loads(v)
                cache_hits += 1
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid cached data for key", key=k[:32])
                continue
        logger.debug("Cache retrieval completed", hits=cache_hits, misses=len(keys) - cache_hits)
        return out

    async def set_many(self, kv: dict[str, list[float]]) -> None:
        if not kv:
            return
        logger.debug("Caching embeddings", count=len(kv))
        pipe = self._r.pipeline()
        for k, v in kv.items():
            ttl = self._ttl * 2
            pipe.set(k, json.dumps(v).encode("utf-8"), ex=ttl)
        await pipe.execute()
        logger.debug("Embeddings cached successfully")

    async def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics for monitoring."""
        try:
            info = await self._r.info(section="stats")
            stats = {
                "hits": info.get("keyspace_hits", 0),
                "misses": info.get("keyspace_misses", 0),
                "hit_rate": info.get("keyspace_hits", 0)
                / max(1, info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0)),
            }
            logger.debug("Cache stats retrieved", **stats)
            return stats
        except Exception as e:
            logger.error("Failed to retrieve cache stats", error=str(e))
            return {"hits": 0, "misses": 0, "hit_rate": 0.0}
