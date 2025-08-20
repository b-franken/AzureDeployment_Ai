from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from typing import AsyncIterator
from app.events.schemas import DeploymentEvent


class DeploymentManager:
    def __init__(self) -> None:
        self._channels: dict[str, asyncio.Queue[DeploymentEvent]] = defaultdict(
            asyncio.Queue)
        self._seq: dict[str, int] = defaultdict(int)
        self._buffers: dict[str, deque[DeploymentEvent]
                            ] = defaultdict(lambda: deque(maxlen=1000))

    def publish(self, deployment_id: str, event: DeploymentEvent) -> None:
        self._seq[deployment_id] += 1
        event.seq = self._seq[deployment_id]
        self._buffers[deployment_id].append(event)
        self._channels[deployment_id].put_nowait(event)

    @asynccontextmanager
    async def stream(self, deployment_id: str, from_seq: int | None = None) -> AsyncIterator[asyncio.Queue[DeploymentEvent]]:
        q = self._channels[deployment_id]
        if from_seq is not None:
            for e in list(self._buffers[deployment_id]):
                if e.seq > from_seq:
                    q.put_nowait(e)
        yield q
