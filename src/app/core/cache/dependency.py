from __future__ import annotations

import asyncio
import os

from app.ai.nlu.embeddings_classifier import EmbeddingsClassifierService
from app.core.cache.backends.inmemory import InMemoryCache
from app.core.cache.backends.redis_backend import RedisCache
from app.core.cache.hybrid_cache import HybridCache
from app.core.cache.ml_optimizer import EmbeddingsTierOptimizer

_lock = asyncio.Lock()
_instance: HybridCache | None = None


async def get_cache() -> HybridCache:
    global _instance
    if _instance is not None:
        return _instance
    async with _lock:
        if _instance is not None:
            return _instance
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        l1 = InMemoryCache(max_size=int(os.getenv("CACHE_L1_MAX", "20000")))
        l2 = RedisCache(url=redis_url, default_ttl=int(os.getenv("CACHE_TTL", "3600")))
        model = EmbeddingsClassifierService(num_labels=2, ckpt=os.getenv("CACHE_TIER_CKPT"))
        optimizer = EmbeddingsTierOptimizer(model=model, label_to_index=[0, 1])
        _instance = HybridCache([l1, l2], optimizer=optimizer)
        return _instance
