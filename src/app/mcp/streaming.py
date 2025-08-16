from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class StreamingHandler:
    def __init__(self) -> None:
        self._streams: dict[str, asyncio.Queue[str]] = {}

    @asynccontextmanager
    async def stream_deployment(
        self,
        deployment_id: str,
    ) -> AsyncIterator[StreamWriter]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._streams[deployment_id] = queue
        try:
            yield StreamWriter(queue)
        finally:
            self._streams.pop(deployment_id, None)

    async def stream_logs(self, deployment_id: str) -> AsyncIterator[str]:
        if deployment_id not in self._streams:
            yield "No active deployment found"
            return
        queue = self._streams[deployment_id]
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=1.0)
                if message == "END":
                    break
                yield message
            except TimeoutError:
                continue


class StreamWriter:
    def __init__(self, queue: asyncio.Queue[str]) -> None:
        self._queue: asyncio.Queue[str] = queue

    async def send(self, message: str) -> None:
        await self._queue.put(message)

    async def close(self) -> None:
        await self._queue.put("END")
