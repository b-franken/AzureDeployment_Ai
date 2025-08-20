import asyncio
from unittest.mock import AsyncMock, patch

from app.cache.redis_cache import CacheManager


def test_cache_manager_async_context_manages_lifecycle() -> None:
    fake_client = AsyncMock()
    fake_client.ping = AsyncMock()
    fake_client.close = AsyncMock()
    fake_pool = AsyncMock()
    fake_pool.disconnect = AsyncMock()

    async def run() -> None:
        with patch("app.cache.redis_cache.ConnectionPool.from_url", return_value=fake_pool):
            with patch("app.cache.redis_cache.redis.Redis", return_value=fake_client):
                async with CacheManager() as cache:
                    assert cache._client is fake_client

    asyncio.run(run())
    fake_client.close.assert_awaited_once()
    fake_pool.disconnect.assert_awaited_once()
