from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any


class DeploymentManager:
    def __init__(self) -> None:
        self._deployments: dict[str, asyncio.Queue[Any]] = {}

    @asynccontextmanager
    async def stream(
        self,
        deployment_id: str,
        from_seq: int | None = None
    ) -> AsyncIterator[asyncio.Queue[Any]]:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._deployments[deployment_id] = queue
        try:
            yield queue
        finally:
            self._deployments.pop(deployment_id, None)
