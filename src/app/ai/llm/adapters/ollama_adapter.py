from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.ai.types import Message
from app.core.config import get_settings


class OllamaAdapter:
    def __init__(self) -> None:
        s = get_settings()
        self._base = s.llm.ollama_base_url.rstrip("/")

    def name(self) -> str:
        return "ollama"

    def endpoint(self) -> str:
        return f"{self._base}/api/chat"

    def headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def build_payload(self, model: str, messages: list[Message], **kwargs: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": str(m["role"]), "content": str(m["content"])} for m in messages],
            "stream": False,
        }
        payload.update(kwargs)
        return payload

    def extract_text(self, data: dict[str, Any]) -> str:
        msg = data.get("message") or {}
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
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    msg = obj.get("message") or {}
                    piece = msg.get("content") or obj.get("response")
                    if piece:
                        yield str(piece)
                except Exception:
                    continue

    async def chat_raw(
        self, client: httpx.AsyncClient, model: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]]:
        stream_mode = kwargs.pop("stream", False)

        if not stream_mode:
            payload = {"model": model, "messages": messages, **kwargs}
            resp = await client.post(self.endpoint(), json=payload, headers=self.headers())
            resp.raise_for_status()
            return resp.json()

        payload = {"model": model, "messages": messages, "stream": True, **kwargs}
        async with client.stream(
            "POST", self.endpoint(), json=payload, headers=self.headers()
        ) as r:
            r.raise_for_status()
            chunks: list[dict[str, Any]] = []
            async for line in r.aiter_lines():
                if line:
                    try:
                        chunks.append(json.loads(line))
                    except Exception:
                        continue
            return chunks
