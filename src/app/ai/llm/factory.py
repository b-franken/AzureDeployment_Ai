from __future__ import annotations

import httpx

from app.ai.llm.base import LLMProvider
from app.ai.llm.gemini_provider import GeminiProvider
from app.ai.llm.ollama_provider import OllamaProvider
from app.ai.llm.openai_provider import OpenAIProvider
from app.config import (
    GEMINI_MODEL,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_MODEL,
)

_OPENAI_MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-5", "gpt-5.5-preview"]

_GEMINI_MODELS = ["gemini-1.5-pro", "gemini-1.5-flash"]

_FALLBACK_OLLAMA_MODELS = ["llama3.1", "mistral", "gemma"]


def available_providers() -> list[str]:
    return ["openai", "gemini", "ollama"]


def _ollama_models() -> list[str]:
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return [
                m["name"] for m in data.get("models", []) if "name" in m
            ] or _FALLBACK_OLLAMA_MODELS
    except Exception:
        return _FALLBACK_OLLAMA_MODELS


def available_models(provider: str) -> list[str]:
    name = provider.lower()
    if name == "openai":
        return _OPENAI_MODELS
    if name == "gemini":
        return _GEMINI_MODELS
    if name == "ollama":
        return _ollama_models()
    return []


def get_provider_and_model(
    provider: str | None = None, model: str | None = None
) -> tuple[LLMProvider, str]:
    selected_provider = (provider or LLM_PROVIDER).lower()
    if selected_provider not in available_providers():
        selected_provider = "ollama"

    def select_model(available: list[str], configured: str, requested: str | None) -> str:
        if requested in available:
            return requested
        if configured in available:
            return configured
        return available[0]

    if selected_provider == "openai":
        return OpenAIProvider(), select_model(_OPENAI_MODELS, OPENAI_MODEL, model)
    if selected_provider == "gemini":
        return GeminiProvider(), select_model(_GEMINI_MODELS, GEMINI_MODEL, model)
    if selected_provider == "ollama":
        return OllamaProvider(), select_model(_ollama_models(), OLLAMA_MODEL, model)

    raise RuntimeError(f"Unsupported LLM provider: {selected_provider}")
