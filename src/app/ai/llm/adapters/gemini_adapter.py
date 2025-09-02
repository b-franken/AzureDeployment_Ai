from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.ai.types import Message
from app.core.config import get_settings


def _to_parts(text: str) -> list[dict[str, str]]:
    return [{"text": text}]


def _to_gemini_messages(messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for m in messages:
        role = str(m["role"])
        content = str(m["content"])
        if role == "user":
            result.append({"role": "user", "parts": _to_parts(content)})
        elif role == "assistant":
            result.append({"role": "model", "parts": _to_parts(content)})
        else:
            result.append({"role": "user", "parts": _to_parts(content)})
    return result


class GeminiAdapter:
    def __init__(self) -> None:
        s = get_settings()
        if not s.llm.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY not configured")
        self._base = "https://generativelanguage.googleapis.com"  # Default Gemini API base
        if s.llm.gemini_api_key is None:
            raise RuntimeError("GEMINI_API_KEY is None")
        self._key = s.llm.gemini_api_key.get_secret_value()

    def name(self) -> str:
        return "gemini"

    def endpoint(self) -> str:
        return f"{self._base}/v1/models"

    def headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def build_payload(self, model: str, messages: list[Message], **kwargs: Any) -> dict[str, Any]:
        return {"contents": _to_gemini_messages(messages), **kwargs}

    def extract_text(self, data: dict[str, Any]) -> str:
        cands = data.get("candidates") or []
        if not cands:
            return ""
        content = cands[0].get("content") or {}
        parts = content.get("parts") or []
        texts = [str(p.get("text") or "") for p in parts if isinstance(p, dict)]
        return "".join(texts)

    async def stream(
        self, client: httpx.AsyncClient, model: str, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[str]:
        url = f"{self.endpoint()}/{model}:streamGenerateContent?alt=sse&key={self._key}"
        payload = self.build_payload(model, messages, **kwargs)
        async with client.stream("POST", url, json=payload, headers=self.headers()) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    cands = obj.get("candidates") or []
                    if not cands:
                        continue
                    content = cands[0].get("content") or {}
                    parts = content.get("parts") or []
                    for p in parts:
                        piece = p.get("text")
                        if piece:
                            yield str(piece)
                except Exception:
                    continue

    async def chat_raw(
        self, client: httpx.AsyncClient, model: str, messages: list[Message], **kwargs: Any
    ) -> dict[str, Any]:
        gemini_messages = _to_gemini_messages(messages)
        url = f"{self.endpoint()}/{model}:generateContent?key={self._key}"
        payload = {"contents": gemini_messages, **kwargs}
        resp = await client.post(url, json=payload, headers=self.headers())
        resp.raise_for_status()
        response_data: dict[str, Any] = resp.json()
        return response_data
