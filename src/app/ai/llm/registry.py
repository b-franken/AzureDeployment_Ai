from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.core.config import OLLAMA_BASE_URL
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ProviderAdapter:
    name: str
    list_models: Callable[[], list[str]]
    fallback: list[str]


class ModelRegistry:
    """
    Dynamic model registry with TTL caching per provider.
    Providers register a list_models() adapter; we fall back safely if discovery fails.
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[list[str], float]] = {}
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def available_models(self, provider: str) -> list[str]:
        key = provider.lower()
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[1] < self._ttl:
            return cached[0]
        try:
            adapter = self._adapters[key]
        except KeyError:
            return []
        models: list[str] = adapter.fallback
        try:
            discovered = adapter.list_models()
            if discovered:
                models = discovered
        except Exception as exc:
            logger.debug("Failed to list models for %s: %s", provider, exc)
        self._cache[key] = (models, now)
        return models

    @staticmethod
    def _ollama_models() -> list[str]:
        """Fetch Ollama models - only call when actually needed."""
        defaults = ["llama3.1", "mistral", "gemma"]

        from app.core.config import LLM_PROVIDER

        if LLM_PROVIDER.lower() != "ollama":
            logger.debug("Ollama not selected as provider, returning defaults without HTTP call")
            return defaults

        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                items = data.get("models", [])
                names: list[str] = []
                for m in items:
                    if isinstance(m, dict) and "name" in m:
                        names.append(m["name"])
                return names or defaults
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("Failed to fetch Ollama models: %s", exc)
            return defaults


_registry = ModelRegistry(ttl_seconds=300)


def registry() -> ModelRegistry:
    return _registry
