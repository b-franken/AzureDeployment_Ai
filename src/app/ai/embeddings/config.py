from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmbeddingsConfig:
    enable: bool = os.getenv("ENABLE_CLASSIFIER", "0").lower() in {"1", "true", "yes"}
    azure_base_url: str = os.getenv("AZURE_OPENAI_BASE_URL", "")
    azure_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    azure_api_key: str | None = os.getenv("AZURE_OPENAI_API_KEY")
    deployment: str = os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", "text-embedding-3-small")
    batch_size: int = int(os.getenv("EMB_BATCH_SIZE", "64"))
    max_concurrency: int = int(os.getenv("EMB_MAX_CONCURRENCY", "2"))
    ttl_seconds: int = int(os.getenv("EMB_CACHE_TTL_SECONDS", "1800"))
    redis_url: str | None = os.getenv("REDIS_URL")
    req_token_budget: int = int(os.getenv("EMB_REQ_TOKEN_BUDGET", "6000"))
    req_call_budget: int = int(os.getenv("EMB_REQ_CALL_BUDGET", "3"))
    normalize: bool = True
