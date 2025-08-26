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
    batch_size: int = int(os.getenv("EMB_BATCH_SIZE", "128"))  # Increased default batch size
    max_concurrency: int = int(os.getenv("EMB_MAX_CONCURRENCY", "3"))  # Slightly higher concurrency
    ttl_seconds: int = int(os.getenv("EMB_CACHE_TTL_SECONDS", "3600"))  # Longer cache TTL (1 hour)
    # New settings for intelligent batching
    batch_wait_ms: int = int(
        os.getenv("EMB_BATCH_WAIT_MS", "50")
    )  # Wait up to 50ms to collect more texts for batching
    enable_dynamic_batching: bool = os.getenv("EMB_ENABLE_DYNAMIC_BATCHING", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    redis_url: str | None = os.getenv("REDIS_URL")
    req_token_budget: int = int(os.getenv("EMB_REQ_TOKEN_BUDGET", "6000"))
    req_call_budget: int = int(os.getenv("EMB_REQ_CALL_BUDGET", "3"))
    normalize: bool = True
    # Use local embeddings for classification in development
    use_local_for_classification: bool = os.getenv(
        "USE_LOCAL_EMBEDDINGS_FOR_CLASSIFICATION", "true"
    ).lower() in {"1", "true", "yes"}
    local_embedding_model: str = os.getenv(
        "LOCAL_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )
