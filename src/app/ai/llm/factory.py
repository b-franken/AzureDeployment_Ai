from __future__ import annotations

import time

import httpx

from app.ai.llm.base import LLMProvider
from app.ai.llm.gemini_provider import GeminiProvider
from app.ai.llm.ollama_provider import OllamaProvider
from app.ai.llm.openai_provider import OpenAIProvider
from app.core.config import (
    GEMINI_MODEL,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_MODEL,
)

_OPENAI_MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-5", "gpt-5.5-preview"]

_GEMINI_MODELS = ["gemini-1.5-pro", "gemini-1.5-flash"]

_FALLBACK_OLLAMA_MODELS = ["llama3.1", "mistral", "gemma"]

_OLLAMA_MODELS_CACHE: tuple[list[str], float] | None = None
_OLLAMA_MODELS_TTL = 300  # seconds


def available_providers() -> list[str]:
    return ["openai", "gemini", "ollama"]


async def _ollama_models() -> list[str]:
    global _OLLAMA_MODELS_CACHE
    now = time.time()
    if _OLLAMA_MODELS_CACHE and now - _OLLAMA_MODELS_CACHE[1] < _OLLAMA_MODELS_TTL:
        return _OLLAMA_MODELS_CACHE[0]
    models = _FALLBACK_OLLAMA_MODELS
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            items = data.get("models", [])
            if items and isinstance(items, list):
                model_names: list[str] = []
                for m in items:
                    if isinstance(m, dict) and "name" in m:
                        model_names.append(m["name"])
                if model_names:
                    models = model_names
    except Exception:
        pass
    _OLLAMA_MODELS_CACHE = (models, now)
    return models


async def available_models(provider: str) -> list[str]:
    name = provider.lower()
    if name == "openai":
        return _OPENAI_MODELS
    if name == "gemini":
        return _GEMINI_MODELS
    if name == "ollama":
        return await _ollama_models()
    return []


async def get_provider_and_model(
    provider: str | None = None, model: str | None = None
) -> tuple[LLMProvider, str]:
    selected_provider = (provider or LLM_PROVIDER).lower()
    if selected_provider not in available_providers():
        selected_provider = "ollama"

    def select_model(available: list[str], configured: str, requested: str | None) -> str:
        if requested and requested in available:
            return requested
        if configured in available:
            return configured
        return available[0] if available else configured

    if selected_provider == "openai":
        return OpenAIProvider(), select_model(_OPENAI_MODELS, OPENAI_MODEL, model)
    if selected_provider == "gemini":
        return GeminiProvider(), select_model(_GEMINI_MODELS, GEMINI_MODEL, model)
    if selected_provider == "ollama":
        models = await _ollama_models()
        return OllamaProvider(), select_model(models, OLLAMA_MODEL, model)

    raise RuntimeError(f"Unsupported LLM provider: {selected_provider}")
