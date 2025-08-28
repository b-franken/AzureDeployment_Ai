from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

try:
    from redis.asyncio import Redis
except Exception:  # noqa: BLE001
    Redis = None  # type: ignore[assignment,misc]


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
            raise RuntimeError("redis missing")
        self._r = Redis.from_url(url, decode_responses=False)
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    async def get_many(self, keys: list[str]) -> dict[str, list[float]]:
        if not keys:
            return {}
        async with self._lock:
            vals = await self._r.mget(keys)
        out: dict[str, list[float]] = {}
        for k, v in zip(keys, vals, strict=False):
            if v is None:
                continue
            try:
                out[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):

                continue
        return out

    async def set_many(self, kv: dict[str, list[float]]) -> None:
        if not kv:
            return
        pipe = self._r.pipeline()
        for k, v in kv.items():

            ttl = self._ttl * 2
            pipe.set(k, json.dumps(v).encode("utf-8"), ex=ttl)
        await pipe.execute()

    async def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics for monitoring."""
        try:
            info = await self._r.info(section="stats")
            return {
                "hits": info.get("keyspace_hits", 0),
                "misses": info.get("keyspace_misses", 0),
                "hit_rate": info.get("keyspace_hits", 0)
                / max(1, info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0)),
            }
        except Exception:
            return {"hits": 0, "misses": 0, "hit_rate": 0.0}
