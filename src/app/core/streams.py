from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

END_MARKER: Final[str] = "__STREAM_END__"


class StreamWriter:
    def __init__(self, subscribers: set[asyncio.Queue[str]]) -> None:
        self._subscribers = subscribers

    async def send(self, message: str) -> None:
        if not self._subscribers:
            return
        await asyncio.gather(*(q.put(message) for q in list(self._subscribers)))

    async def close(self) -> None:
        if not self._subscribers:
            return
        await asyncio.gather(*(q.put(END_MARKER) for q in list(self._subscribers)))


class StreamingHandler:
    def __init__(self) -> None:
        self._streams: dict[str, set[asyncio.Queue[str]]] = {}

    @asynccontextmanager
    async def stream(self, key: str) -> AsyncIterator[StreamWriter]:
        subs = self._streams.setdefault(key, set())
        try:
            yield StreamWriter(subs)
        finally:
            await StreamWriter(subs).close()
            self._streams.pop(key, None)

    @asynccontextmanager
    async def stream_deployment(self, deployment_id: str) -> AsyncIterator[StreamWriter]:
        async with self.stream(deployment_id) as writer:
            yield writer

    async def stream_logs(self, key: str) -> AsyncIterator[str]:
        subs = self._streams.get(key)
        if subs is None:
            yield "No active stream"
            return
        q: asyncio.Queue[str] = asyncio.Queue()
        subs.add(q)
        try:
            while True:
                message = await q.get()
                if message == END_MARKER:
                    break
                yield message
        finally:
            subs.discard(q)


streaming_handler = StreamingHandler()
