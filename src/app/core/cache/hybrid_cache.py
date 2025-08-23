from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import Any

from opentelemetry import trace
from prometheus_client import Counter, Histogram

from app.core.cache.base import CacheBackend
from app.core.cache.ml_optimizer import CacheTierOptimizer, EwmaOptimizer
from app.core.logging import get_logger

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)

CACHE_HITS = Counter("cache_hits_total", "Cache hits", labelnames=("level",))
CACHE_MISSES = Counter("cache_misses_total", "Cache misses", labelnames=("reason",))
CACHE_OPS = Counter("cache_ops_total", "Cache ops", labelnames=("op", "success"))
CACHE_LATENCY = Histogram(
    "cache_op_duration_seconds",
    "Cache op latency seconds",
    labelnames=("op", "level", "success"),
    buckets=(0.0005, 0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)


class HybridCache:
    def __init__(
        self, levels: Sequence[CacheBackend], optimizer: CacheTierOptimizer | None = None
    ) -> None:
        if not levels:
            raise ValueError("levels required")
        self.levels = list(levels)
        self._optimizer: CacheTierOptimizer = optimizer or EwmaOptimizer()

    async def get(self, key: str) -> Any | None:
        start = time.perf_counter()
        with tracer.start_as_current_span("cache.get") as span:
            span.set_attribute("cache.key_len", len(key))
            predicted = await self._optimizer.predict_index(key, len(self.levels))
            tried: set[int] = set()
            value: Any | None = None
            hit_index = -1
            for idx in [predicted, *[i for i in range(len(self.levels)) if i != predicted]]:
                if idx in tried:
                    continue
                tried.add(idx)
                try:
                    v = await self.levels[idx].get(key)
                    if v is not None:
                        value = v
                        hit_index = idx
                        break
                except Exception as exc:
                    logger.warning(
                        "cache.get.error",
                        extra={"key_hash": hash(key), "level": idx, "error": str(exc)},
                        exc_info=True,
                    )
                    continue
            if value is None:
                await self._optimizer.observe_miss(key)
                CACHE_MISSES.labels(reason="not_found").inc()
                CACHE_OPS.labels(op="get", success="false").inc()
                CACHE_LATENCY.labels(op="get", level="none", success="false").observe(
                    time.perf_counter() - start
                )
                return None
            if hit_index > 0:
                try:
                    async with asyncio.TaskGroup() as tg:
                        for j in range(hit_index):
                            tg.create_task(self.levels[j].set(key, value))
                except Exception as exc:
                    logger.debug(
                        "cache.promote.error",
                        extra={"key_hash": hash(key), "from": hit_index, "error": str(exc)},
                        exc_info=True,
                    )
            await self._optimizer.observe_hit(key)
            CACHE_HITS.labels(level=str(hit_index)).inc()
            CACHE_OPS.labels(op="get", success="true").inc()
            CACHE_LATENCY.labels(op="get", level=str(hit_index), success="true").observe(
                time.perf_counter() - start
            )
            return value

    async def set(
        self, key: str, value: Any, ttl: int | None = None, tier_index: int | None = None
    ) -> bool:
        start = time.perf_counter()
        with tracer.start_as_current_span("cache.set") as span:
            span.set_attribute("cache.key_len", len(key))
            idx = (
                tier_index
                if tier_index is not None
                else await self._optimizer.recommend_index(key, value, len(self.levels))
            )
            tasks: list[asyncio.Task[bool]] = []
            for i, lvl in enumerate(self.levels):
                if tier_index is None or i <= idx:
                    tasks.append(asyncio.create_task(lvl.set(key, value, ttl)))
            ok = False
            for t in tasks:
                try:
                    ok |= bool(await t)
                except Exception as exc:
                    logger.warning(
                        "cache.set.error",
                        extra={"key_hash": hash(key), "error": str(exc)},
                        exc_info=True,
                    )
            CACHE_OPS.labels(op="set", success=str(ok).lower()).inc()
            CACHE_LATENCY.labels(op="set", level=str(idx), success=str(ok).lower()).observe(
                time.perf_counter() - start
            )
            return ok

    async def delete(self, *keys: str) -> int:
        start = time.perf_counter()
        with tracer.start_as_current_span("cache.delete"):
            async with asyncio.TaskGroup() as tg:
                for lvl in self.levels:
                    tg.create_task(lvl.delete(*keys))
            count = 0
            for lvl in self.levels:
                try:
                    count += await lvl.exists(*keys)
                except Exception as exc:
                    logger.warning("cache.delete.error", extra={"error": str(exc)}, exc_info=True)
            CACHE_OPS.labels(op="delete", success="true").inc()
            CACHE_LATENCY.labels(op="delete", level="all", success="true").observe(
                time.perf_counter() - start
            )
            return count

    async def exists(self, *keys: str) -> int:
        total = 0
        for lvl in self.levels:
            try:
                total += await lvl.exists(*keys)
            except Exception as exc:
                logger.debug("cache.exists.error", extra={"error": str(exc)}, exc_info=True)
        return 1 if total > 0 else 0

    async def expire(self, key: str, seconds: int) -> bool:
        ok = False
        async with asyncio.TaskGroup() as tg:
            for lvl in self.levels:
                tg.create_task(lvl.expire(key, seconds))
        for lvl in self.levels:
            try:
                ok |= await lvl.exists(key) > 0
            except Exception as exc:
                logger.debug("cache.expire.error", extra={"error": str(exc)}, exc_info=True)
        return ok

    async def incr(self, key: str, amount: int = 1) -> int:
        value = 0
        for lvl in reversed(self.levels):
            try:
                value = await lvl.incr(key, amount)
                if value:
                    break
            except Exception as exc:
                logger.debug("cache.incr.error", extra={"error": str(exc)}, exc_info=True)
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
        value: Any | None = None
        hit_index = -1
        for i, lvl in enumerate(self.levels):
            try:
                value = await lvl.hget(name, key)
            except Exception:
                continue
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
        async with asyncio.TaskGroup() as tg:
            for lvl in self.levels:
                tg.create_task(lvl.lpush(key, *values))
        n = 0
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
