from __future__ import annotations
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class StreamWriter:
    def __init__(self, subscribers: set[asyncio.Queue[str]]) -> None:
        self._subscribers = subscribers

    async def send(self, message: str) -> None:
        for q in list(self._subscribers):
            await q.put(message)

    async def close(self) -> None:
        for q in list(self._subscribers):
            await q.put("END")


class StreamingHandler:
    def __init__(self) -> None:
        self._streams: dict[str, set[asyncio.Queue[str]]] = {}

    @asynccontextmanager
    async def stream_deployment(self, deployment_id: str) -> AsyncIterator[StreamWriter]:
        subs = self._streams.setdefault(deployment_id, set())
        try:
            yield StreamWriter(subs)
        finally:
            await StreamWriter(subs).close()
            self._streams.pop(deployment_id, None)

    async def stream_logs(self, deployment_id: str) -> AsyncIterator[str]:
        subs = self._streams.get(deployment_id)
        if subs is None:
            yield "No active deployment found"
            return
        q: asyncio.Queue[str] = asyncio.Queue()
        subs.add(q)
        try:
            while True:
                message = await asyncio.wait_for(q.get(), timeout=30.0)
                if message == "END":
                    break
                yield message
        finally:
            subs.discard(q)


streaming_handler = StreamingHandler()
