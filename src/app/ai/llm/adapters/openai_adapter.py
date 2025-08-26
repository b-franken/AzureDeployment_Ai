# src/app/ai/llm/adapters/openai_adapter.py
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.ai.types import Message
from app.core.config import get_settings


class OpenAIAdapter:
    def __init__(self) -> None:
        s = get_settings()
        if not s.llm.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        self._base = s.llm.openai_api_base.rstrip("/")
        self._key = s.llm.openai_api_key.get_secret_value()

    def name(self) -> str:
        return "openai"

    def endpoint(self) -> str:
        return f"{self._base}/chat/completions"

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _sanitize_kwargs(self, **kwargs: Any) -> dict[str, Any]:
        allowed = {
            "temperature",
            "top_p",
            "n",
            "max_tokens",
            "presence_penalty",
            "frequency_penalty",
            "stop",
            "stream",
            "response_format",
            "tools",
            "tool_choice",
            "seed",
            "logit_bias",
            "logprobs",
            "top_logprobs",
        }
        out: dict[str, Any] = {}
        for k, v in kwargs.items():
            if k in allowed and v is not None and v != "":
                out[k] = v
        if not out.get("stream"):
            out.pop("stream", None)
        return out

    def build_payload(self, model: str, messages: list[Message], **kwargs: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": str(m["role"]), "content": str(m["content"])} for m in messages],
        }
        payload.update(self._sanitize_kwargs(**kwargs))
        return payload

    def extract_text(self, data: dict[str, Any]) -> str:
        ch = (data.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        return str(msg.get("content") or "")

    async def stream(
        self, client: httpx.AsyncClient, model: str, messages: list[Message], **kwargs: Any
    ) -> AsyncIterator[str]:
        payload = self.build_payload(model, messages, stream=True, **kwargs)
        async with client.stream(
            "POST", self.endpoint(), json=payload, headers=self.headers()
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    choice = (obj.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield str(piece)
                except Exception:
                    continue

    async def chat_raw(
        self, client: httpx.AsyncClient, model: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        payload = self.build_payload(model, messages, **kwargs)
        resp = await client.post(self.endpoint(), json=payload, headers=self.headers())
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = resp.text
            raise httpx.HTTPStatusError(
                f"{e}. body={detail}", request=e.request, response=e.response
            ) from e
        return resp.json()
