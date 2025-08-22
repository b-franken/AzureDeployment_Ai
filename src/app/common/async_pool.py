from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterable
from typing import Any


async def bounded_gather(*aws: Awaitable[Any], limit: int = 8) -> list[Any]:
    if not aws:
        return []
    sem = asyncio.Semaphore(max(1, int(limit)))

    async def _run(coro: Awaitable[Any]) -> Any:
        async with sem:
            return await coro

    tasks: list[asyncio.Task[Any]] = [asyncio.create_task(_run(c)) for c in aws]
    try:
        return await asyncio.gather(*tasks, return_exceptions=False)
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()


async def amap(fn: callable, items: Iterable[Any], limit: int = 8) -> list[Any]:
    coros: list[Awaitable[Any]] = [fn(x) for x in items]
    return await bounded_gather(*coros, limit=limit)
