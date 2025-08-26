from __future__ import annotations

import asyncio
import hashlib
import json

try:
    from redis.asyncio import Redis
except Exception:  # noqa: BLE001
    Redis = None  # type: ignore[assignment,misc]


def normkey(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


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
            out[k] = json.loads(v)
        return out

    async def set_many(self, kv: dict[str, list[float]]) -> None:
        if not kv:
            return
        pipe = self._r.pipeline()
        for k, v in kv.items():
            pipe.set(k, json.dumps(v).encode("utf-8"), ex=self._ttl)
        await pipe.execute()
