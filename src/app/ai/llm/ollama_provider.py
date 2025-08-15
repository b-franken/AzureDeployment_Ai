from __future__ import annotations

import httpx

from app.ai.llm.base import LLMProvider
from app.ai.llm.utils import retry_async
from app.ai.types import Message
from app.config import (
    OLLAMA_BASE_URL,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_BACKOFF_SECONDS,
    RETRY_MAX_ATTEMPTS,
)


class OllamaProvider(LLMProvider):
    def __init__(self) -> None:
        self._base = OLLAMA_BASE_URL.rstrip("/")

    async def chat(self, model: str, messages: list[Message]) -> str:
        payload = {"model": model, "messages": messages, "stream": False}

        async def _call() -> str:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                r = await client.post(f"{self._base}/api/chat", json=payload)
                r.raise_for_status()
                data = r.json()
                return data["message"]["content"].strip()

        return await retry_async(_call, RETRY_MAX_ATTEMPTS, RETRY_BACKOFF_SECONDS)
