from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar, cast

from app.core.logging import get_logger

T = TypeVar("T")
R = TypeVar("R")

logger = get_logger(__name__)


async def bounded_gather(*aws: Awaitable[R], limit: int = 8) -> list[R]:
    if not aws:
        return []
    lim = max(1, int(limit))
    sem = asyncio.Semaphore(lim)

    async def _run(coro: Awaitable[R]) -> R:
        async with sem:
            return await coro

    tasks: list[asyncio.Task[R]] = [asyncio.create_task(_run(c)) for c in aws]
    start = time.perf_counter()
    try:
        results = await asyncio.gather(*tasks)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.debug(
            "bounded_gather completed", tasks=len(tasks), limit=lim, duration_ms=duration_ms
        )
        return cast(list[R], results)
    except Exception as exc:
        logger.error(
            "bounded_gather failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
            limit=lim,
            tasks=len(tasks),
            exc_info=True,
        )
        raise
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()


async def amap(fn: Callable[[T], Awaitable[R]], items: Iterable[T], limit: int = 8) -> list[R]:
    lim = max(1, int(limit))
    coros: list[Awaitable[R]] = []
    for x in items:
        try:
            c = fn(x)
        except Exception as exc:
            logger.error(
                "amap function invocation failed",
                item_type=type(x).__name__,
                error_type=type(exc).__name__,
                error_message=str(exc),
                exc_info=True,
            )
            raise
        if not isinstance(c, Awaitable):
            raise TypeError("amap expected fn to return an awaitable")
        coros.append(c)
    logger.debug("amap dispatch", count=len(coros), limit=lim)
    return await bounded_gather(*coros, limit=lim)
