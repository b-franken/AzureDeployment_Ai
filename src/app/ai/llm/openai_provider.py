from __future__ import annotations

import httpx

from app.ai.llm.base import LLMProvider
from app.ai.llm.utils import retry_async
from app.ai.types import Message
from app.config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_BACKOFF_SECONDS,
    RETRY_MAX_ATTEMPTS,
)


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI not configured")
        self._headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        self._base = OPENAI_BASE_URL.rstrip("/")

    async def chat(self, model: str, messages: list[Message]) -> str:
        async def _call() -> str:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                r = await client.post(
                    f"{self._base}/chat/completions",
                    headers=self._headers,
                    json={"model": model, "messages": messages},
                )
                r.raise_for_status()
                data = r.json()
                return data["choices"][0]["message"]["content"].strip()

        return await retry_async(_call, RETRY_MAX_ATTEMPTS, RETRY_BACKOFF_SECONDS)

    async def chat_raw(
        self,
        model: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | None = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {"model": model, "messages": messages}
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        async def _call() -> dict[str, object]:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                r = await client.post(
                    f"{self._base}/chat/completions", headers=self._headers, json=payload
                )
                r.raise_for_status()
                return r.json()

        return await retry_async(_call, RETRY_MAX_ATTEMPTS, RETRY_BACKOFF_SECONDS)
