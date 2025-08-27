from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Lock
from time import monotonic

import httpx

from app.ai.llm.adapters.gemini_adapter import GeminiAdapter
from app.ai.llm.adapters.ollama_adapter import OllamaAdapter
from app.ai.llm.adapters.openai_adapter import OpenAIAdapter
from app.ai.llm.base import LLMProvider
from app.ai.llm.registry import ProviderAdapter, registry
from app.ai.llm.unified_provider import UnifiedLLMProvider
from app.core.config import GEMINI_MODEL, LLM_PROVIDER, OLLAMA_MODEL, OPENAI_MODEL

logger = logging.getLogger(__name__)

_reg = registry()

_TTL_SECONDS: float = 600.0
_CACHE: dict[str, tuple[float, list[str]]] = {}
_CACHE_LOCK = Lock()


def _get_cached(key: str, fetch: Callable[[], list[str]]) -> list[str]:
    now = monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and entry[0] > now:
            return entry[1]
    result = fetch()
    with _CACHE_LOCK:
        _CACHE[key] = (now + _TTL_SECONDS, result)
    return result


def invalidate_model_cache(provider: str | None = None) -> None:
    with _CACHE_LOCK:
        if provider:
            _CACHE.pop(provider, None)
        else:
            _CACHE.clear()


def _fetch_openai_models() -> list[str]:
    fallback = ["gpt-4o-mini", "gpt-4o", "gpt-5"]
    try:
        from app.core.config import get_settings

        s = get_settings()
        api_key = s.llm.openai_api_key.get_secret_value() if s.llm.openai_api_key else None
        if not api_key:
            return fallback
        base = s.llm.openai_api_base.rstrip("/")
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as c:
            r = c.get(f"{base}/models", headers={"Authorization": f"Bearer {api_key}"})
            if r.status_code != 200:
                return fallback
            data = r.json()
            models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
            return models or fallback
    except Exception:
        return fallback


def _openai_list() -> list[str]:
    return _get_cached("openai_models", _fetch_openai_models)


def _gemini_list() -> list[str]:
    return ["gemini-1.5-flash", "gemini-1.5-pro"]


def _ollama_list() -> list[str]:
    return _reg._ollama_models()


_reg.register(ProviderAdapter("openai", _openai_list, ["gpt-4o-mini", "gpt-4o", "gpt-5"]))
_reg.register(ProviderAdapter("gemini", _gemini_list, ["gemini-1.5-pro", "gemini-1.5-flash"]))
_reg.register(ProviderAdapter("ollama", _ollama_list, ["llama3.1", "mistral", "gemma"]))


def available_providers() -> list[str]:
    return ["openai", "gemini", "ollama"]


async def available_models(provider: str) -> list[str]:
    return _reg.available_models(provider)


async def get_provider_and_model(
    provider: str | None = None, model: str | None = None
) -> tuple[LLMProvider, str]:
    selected_provider = (provider or LLM_PROVIDER).lower()
    available = available_providers()

    if selected_provider not in available:
        logger.warning(
            f"Requested provider '{selected_provider}' not in available providers {available}. "
            "Using OpenAI as fallback instead of Ollama."
        )
        selected_provider = "openai" if "openai" in available else available[0]

    logger.info(
        f"Selected LLM provider: {selected_provider} "
        f"(requested: {provider}, config default: {LLM_PROVIDER})"
    )

    def select_model(available: list[str], configured: str, requested: str | None) -> str:
        logger.info(
            "Model selection: requested='%s', configured='%s', available=%s",
            requested,
            configured,
            available,
        )

        if requested and requested in available:
            logger.info(f"Using requested model: {requested}")
            return requested
        if requested:
            logger.warning(
                (
                    "Requested model '%s' not in available models %s. "
                    "Falling back to configured model."
                ),
                requested,
                available,
            )

        if configured in available:
            logger.info(f"Using configured model: {configured}")
            return configured
        if configured:
            logger.warning(
                ("Configured model '%s' not in available models %s. Using first available model."),
                configured,
                available,
            )

        fallback = available[0] if available else configured
        logger.info(f"Using fallback model: {fallback}")
        return fallback

    if selected_provider == "openai":
        models = await available_models("openai")
        return UnifiedLLMProvider(OpenAIAdapter()), select_model(models, OPENAI_MODEL, model)
    if selected_provider == "gemini":
        models = await available_models("gemini")
        return UnifiedLLMProvider(GeminiAdapter()), select_model(models, GEMINI_MODEL, model)
    if selected_provider == "ollama":
        models = await available_models("ollama")
        return UnifiedLLMProvider(OllamaAdapter()), select_model(models, OLLAMA_MODEL, model)

    raise RuntimeError(f"Unsupported LLM provider: {selected_provider}")
