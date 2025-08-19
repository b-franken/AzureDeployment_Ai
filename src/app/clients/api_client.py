# src/app/clients/api_client.py
from __future__ import annotations

import time
from collections.abc import Sequence

import httpx

from app.core.config import get_env_var

API_BASE_URL = get_env_var("API_BASE_URL", "http://localhost:8000")
API_TIMEOUT = float(get_env_var("API_TIMEOUT_SECONDS", "30"))

API_TOKEN = get_env_var("API_TOKEN", "").strip()
API_AUTH_EMAIL = get_env_var("API_AUTH_EMAIL", "").strip()
API_AUTH_PASSWORD = get_env_var("API_AUTH_PASSWORD", "").strip()

_token: str | None = None
_token_exp: float = 0.0


async def _ensure_auth(client: httpx.AsyncClient) -> dict[str, str]:
    if API_TOKEN:
        return {"Authorization": f"Bearer {API_TOKEN}"}

    global _token, _token_exp
    now = time.time()
    if _token and now < _token_exp - 30:
        return {"Authorization": f"Bearer {_token}"}

    if not API_AUTH_EMAIL or not API_AUTH_PASSWORD:
        return {}

    r = await client.post(
        "/api/auth/login",
        json={"email": API_AUTH_EMAIL, "password": API_AUTH_PASSWORD},
    )
    r.raise_for_status()
    data = r.json()
    _token = data["access_token"]
    _token_exp = now + float(data.get("expires_in", 3600))
    return {"Authorization": f"Bearer {_token}"}


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
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=API_TIMEOUT) as client:
        headers = await _ensure_auth(client)
        if not stream:
            r = await client.post("/api/chat", json=payload, headers=headers)
            r.raise_for_status()
            return r.json()["output"]
        async with client.stream(
            "POST", "/api/chat", json=payload, params={"stream": "true"}, headers=headers
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
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=API_TIMEOUT) as client:
        headers = await _ensure_auth(client)
        r = await client.post("/api/review", json=payload, headers=headers)
        r.raise_for_status()
        return r.json()["output"]
