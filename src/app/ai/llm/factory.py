from __future__ import annotations

import httpx
from openai import OpenAI

from app.ai.llm.base import LLMProvider
from app.ai.llm.gemini_provider import GeminiProvider
from app.ai.llm.ollama_provider import OllamaProvider
from app.ai.llm.openai_provider import OpenAIProvider
from app.ai.llm.registry import ProviderAdapter, registry
from app.core.config import (
    GEMINI_MODEL,
    LLM_PROVIDER,
    OLLAMA_MODEL,
    OPENAI_MODEL,
    get_settings,
)

_reg = registry()


def _openai_list() -> list[str]:
    fallback = ["gpt-4o-mini", "gpt-4o", "gpt-5"]
    try:
        settings = get_settings()
        api_key = (
            settings.llm.openai_api_key.get_secret_value()
            if settings.llm.openai_api_key
            else None
        )
        if not api_key:
            return fallback
        client = OpenAI(
            api_key=api_key,
            base_url=settings.llm.openai_api_base,
            max_retries=3,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        resp = client.models.list()
        models = [m.id for m in getattr(
            resp, "data", []) if getattr(m, "id", None)]
        return models if models else fallback
    except Exception:
        return fallback


def _gemini_list() -> list[str]:
    return ["gemini-1.5-flash", "gemini-1.5-pro"]


def _ollama_list() -> list[str]:
    return _reg._ollama_models()


_reg.register(ProviderAdapter("openai", _openai_list,
              ["gpt-4o-mini", "gpt-4o", "gpt-5"]))
_reg.register(ProviderAdapter("gemini", _gemini_list,
              ["gemini-1.5-pro", "gemini-1.5-flash"]))
_reg.register(ProviderAdapter("ollama", _ollama_list,
              ["llama3.1", "mistral", "gemma"]))


def available_providers() -> list[str]:
    return ["openai", "gemini", "ollama"]


async def available_models(provider: str) -> list[str]:
    return _reg.available_models(provider)


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
        models = await available_models("openai")
        return OpenAIProvider(), select_model(models, OPENAI_MODEL, model)
    if selected_provider == "gemini":
        models = await available_models("gemini")
        return GeminiProvider(), select_model(models, GEMINI_MODEL, model)
    if selected_provider == "ollama":
        models = await available_models("ollama")
        return OllamaProvider(), select_model(models, OLLAMA_MODEL, model)

    raise RuntimeError(f"Unsupported LLM provider: {selected_provider}")
