from __future__ import annotations

import asyncio
import re
from typing import Iterable

from openai import AsyncOpenAI

from .cache import RedisCache, normkey
from .config import EmbeddingsConfig
from .context import EmbeddingsBudget, budget_var, req_cache_var
from .tokenizer import estimate_tokens

_ws_re = re.compile(r"\s+")


class EmbeddingsService:
    def __init__(self, cfg: EmbeddingsConfig) -> None:
        self._cfg = cfg
        self._client = AsyncOpenAI(
            base_url=f"{cfg.azure_base_url}/openai", api_key=cfg.azure_api_key, default_headers=None)
        self._api_version = cfg.azure_api_version
        self._sem = asyncio.Semaphore(value=max(1, cfg.max_concurrency))
        self._redis = RedisCache(
            cfg.redis_url, cfg.ttl_seconds) if cfg.redis_url else None

    def _norm(self, text: str) -> str:
        if not self._cfg.normalize:
            return text
        return _ws_re.sub(" ", text.strip())

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        normed = [self._norm(t) for t in texts]
        keys = [normkey(t) for t in normed]
        local = req_cache_var.get()
        hits: dict[str, list[float]] = {k: v for k, v in (
            (k, local.get(k)) for k in keys) if v is not None}
        miss_keys = [k for k in keys if k not in hits]
        miss_texts = [t for t, k in zip(normed, keys) if k in set(miss_keys)]
        if self._redis:
            redis_hits = await self._redis.get_many(miss_keys)
            hits.update(redis_hits)
            miss_keys = [k for k in miss_keys if k not in redis_hits]
            miss_texts = [t for t, k in zip(
                miss_texts, [k for k in keys if k in set(miss_keys)])]
        remaining = list(zip(miss_keys, miss_texts))
        out: dict[str, list[float]] = {}
        out.update(hits)
        if remaining:
            batches = [remaining[i: i + self._cfg.batch_size]
                       for i in range(0, len(remaining), self._cfg.batch_size)]
            for batch in batches:
                spend = estimate_tokens([t for _, t in batch])
                budget = budget_var.get()
                if not budget.can_spend(spend):
                    break
                async with self._sem:
                    res = await self._client.embeddings.create(model=self._cfg.deployment, input=[t for _, t in batch], extra_query={"api-version": self._api_version})
                budget.spend(spend)
                for pair, d in zip(batch, res.data):
                    out[pair[0]] = d.embedding
        local.update(out)
        req_cache_var.set(local)
        if self._redis:
            to_set = {k: v for k, v in out.items()}
            await self._redis.set_many(to_set)
        return [out[k] for k in keys if k in out]
