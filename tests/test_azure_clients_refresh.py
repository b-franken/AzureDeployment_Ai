import asyncio
import time
from unittest.mock import patch

from app.tools.azure import clients as azure_clients


class DummyClient:
    def __init__(self) -> None:
        self.cred = object()


def test_get_clients_refreshes_expired_entry() -> None:
    async def run() -> None:
        counter = {"count": 0}

        async def fake_build(sid: str):
            counter["count"] += 1
            return DummyClient(), int(time.time()) + 1

        azure_clients._CACHE.clear()
        with patch("app.tools.azure.clients._build_clients", fake_build):
            c1 = await azure_clients.get_clients("sid")
            await asyncio.sleep(1.1)
            c2 = await azure_clients.get_clients("sid")
        assert c1 is not c2
        assert counter["count"] == 2
        azure_clients._CACHE.clear()

    asyncio.run(run())
