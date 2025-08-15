from __future__ import annotations

import os
from collections.abc import Sequence

import httpx

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


async def chat(
    input_text: str,
    memory: Sequence[dict[str, str]] | None = None,
    provider: str | None = None,
    model: str | None = None,
    enable_tools: bool = False,
    preferred_tool: str | None = None,
    allowlist: Sequence[str] | None = None,
    stream: bool = False,
) -> str:
    payload: dict[str, object] = {
        "input": input_text,
        "memory": memory or [],
        "provider": provider,
        "model": model,
        "enable_tools": enable_tools,
        "preferred_tool": preferred_tool,
        "allowlist": list(allowlist or []),
    }
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=None) as client:
        if not stream:
            r = await client.post("/chat", json=payload)
            r.raise_for_status()
            return r.json()["output"]
        async with client.stream(
            "POST", "/chat", json=payload, params={"stream": "true"}
        ) as resp:
            resp.raise_for_status()
            chunks: list[str] = []
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                chunks.append(data)
            return "".join(chunks)


async def review(
    user_input: str,
    assistant_reply: str,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    payload = {
        "user_input": user_input,
        "assistant_reply": assistant_reply,
        "provider": provider,
        "model": model,
    }
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=None) as client:
        r = await client.post("/review", json=payload)
        r.raise_for_status()
        return r.json()["output"]
