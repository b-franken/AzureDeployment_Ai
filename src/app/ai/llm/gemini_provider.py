from __future__ import annotations

import httpx

from app.ai.llm.base import LLMProvider
from app.ai.llm.utils import retry_async
from app.ai.types import Message
from app.config import (
    GEMINI_API_KEY,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_BACKOFF_SECONDS,
    RETRY_MAX_ATTEMPTS,
)


class GeminiProvider(LLMProvider):
    def __init__(self) -> None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI not configured")
        self._key = GEMINI_API_KEY
        self._base = "https://generativelanguage.googleapis.com/v1beta"

    def _to_gemini(self, messages: list[Message]) -> dict[str, object]:
        parts = []
        for m in messages:
            role = "user" if m["role"] in ("system", "user") else "model"
            parts.append({"role": role, "parts": [{"text": m["content"]}]})
        return {"contents": parts}

    async def chat(self, model: str, messages: list[Message]) -> str:
        payload = self._to_gemini(messages)

        async def _call() -> str:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                r = await client.post(
                    f"{self._base}/models/{model}:generateContent",
                    params={"key": self._key},
                    json=payload,
                )
                r.raise_for_status()
                data = r.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()

        return await retry_async(_call, RETRY_MAX_ATTEMPTS, RETRY_BACKOFF_SECONDS)
