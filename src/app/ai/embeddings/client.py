from __future__ import annotations

import asyncio
import re

from openai import AsyncOpenAI

from app.core.logging import get_logger

from .batch_processor import DynamicBatchProcessor
from .cache import RedisCache, normkey
from .config import EmbeddingsConfig
from .context import budget_var, req_cache_var
from .tokenizer import estimate_tokens

logger = get_logger(__name__)

_ws_re = re.compile(r"\s+")


class EmbeddingsService:
    def __init__(self, cfg: EmbeddingsConfig) -> None:
        logger.info(
            "Initializing embeddings service",
            deployment=cfg.deployment,
            max_concurrency=cfg.max_concurrency,
        )
        self._cfg = cfg
        self._client = AsyncOpenAI(
            base_url=f"{cfg.azure_base_url}/openai", api_key=cfg.azure_api_key, default_headers=None
        )
        self._api_version = cfg.azure_api_version
        self._sem = asyncio.Semaphore(value=max(1, cfg.max_concurrency))
        self._redis = RedisCache(cfg.redis_url, cfg.ttl_seconds) if cfg.redis_url else None
        if not cfg.redis_url:
            logger.warning("Redis cache not configured, embeddings will not be cached")

        # Initialize batch processor if dynamic batching is enabled
        self._batch_processor: DynamicBatchProcessor | None = None
        if cfg.enable_dynamic_batching:
            logger.info(
                "Enabling dynamic batching",
                batch_size=cfg.batch_size,
                batch_wait_ms=cfg.batch_wait_ms,
            )
            self._batch_processor = DynamicBatchProcessor(
                embed_fn=self._direct_embed,
                batch_size=cfg.batch_size,
                batch_wait_ms=cfg.batch_wait_ms,
            )
            # Start the batch processor
            asyncio.create_task(self._batch_processor.start())
        else:
            logger.info("Dynamic batching disabled, using direct embedding")

    def _norm(self, text: str) -> str:
        if not self._cfg.normalize:
            return text
        return _ws_re.sub(" ", text.strip())

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Main embedding method that handles caching and batching."""
        if not texts:
            return []

        logger.debug("Processing embedding request", text_count=len(texts))
        # Use batch processor if enabled
        if self._batch_processor:
            result = await self._batch_processor.embed(texts)
            logger.debug(
                "Batch embedding completed",
                input_count=len(texts),
                output_count=len(result),
            )
            return result
        result = await self._direct_embed(texts)
        logger.debug("Direct embedding completed", input_count=len(texts), output_count=len(result))
        return result

    async def _direct_embed(self, texts: list[str]) -> list[list[float]]:
        """Direct embedding method without batch processing (used by batch processor)."""
        if not texts:
            return []
        normed = [self._norm(t) for t in texts]
        keys = [normkey(t) for t in normed]
        local = req_cache_var.get()
        hits: dict[str, list[float]] = {}
        if local is not None:
            hits = {k: v for k, v in ((k, local.get(k)) for k in keys) if v is not None}
        miss_keys = [k for k in keys if k not in hits]
        miss_texts = [t for t, k in zip(normed, keys, strict=False) if k in set(miss_keys)]
        if self._redis:
            redis_hits = await self._redis.get_many(miss_keys)
            hits.update(redis_hits)
            miss_keys = [k for k in miss_keys if k not in redis_hits]
            miss_texts = [
                t
                for t, k in zip(miss_texts, [k for k in keys if k in set(miss_keys)], strict=False)
            ]
        remaining = list(zip(miss_keys, miss_texts, strict=False))
        out: dict[str, list[float]] = {}
        out.update(hits)
        if remaining:
            logger.debug("Processing embeddings not in cache", count=len(remaining))
            batches = [
                remaining[i : i + self._cfg.batch_size]
                for i in range(0, len(remaining), self._cfg.batch_size)
            ]
            for batch_idx, batch in enumerate(batches):
                spend = estimate_tokens([t for _, t in batch])
                budget = budget_var.get()
                if not budget.can_spend(spend):
                    logger.warning(
                        "Budget exhausted, stopping embedding batch processing",
                        batch_idx=batch_idx,
                        spend=spend,
                    )
                    break
                logger.debug(
                    "Processing embedding batch",
                    batch_idx=batch_idx,
                    batch_size=len(batch),
                    tokens=spend,
                )
                async with self._sem:
                    res = await self._client.embeddings.create(
                        model=self._cfg.deployment,
                        input=[t for _, t in batch],
                        extra_query={"api-version": self._api_version},
                    )
                budget.spend(spend)
                for pair, d in zip(batch, res.data, strict=False):
                    out[pair[0]] = d.embedding
                logger.debug(
                    "Embedding batch completed",
                    batch_idx=batch_idx,
                    embeddings_generated=len(batch),
                )
        if local is not None:
            local.update(out)
            req_cache_var.set(local)
        else:
            req_cache_var.set(out)
        if self._redis:
            to_set = {k: v for k, v in out.items()}
            await self._redis.set_many(to_set)
        return [out[k] for k in keys if k in out]
