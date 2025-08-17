from __future__ import annotations

from collections.abc import Sequence

from app.clients.api_client import chat as api_chat
from app.clients.api_client import review as api_review
from app.core.config import get_env_var

USE_API = get_env_var("USE_API", "").lower() in {"1", "true", "yes"} or bool(
    get_env_var("API_BASE_URL")
)


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
    if USE_API:
        return await api_chat(
            input_text,
            memory=memory,
            provider=provider,
            model=model,
            enable_tools=enable_tools,
            preferred_tool=preferred_tool,
            allowlist=allowlist,
            stream=stream,
        )
    from app.ai.tools_router import maybe_call_tool

    mem = list(memory or [])
    return await maybe_call_tool(
        input_text,
        mem,
        provider=provider,
        model=model,
        enable_tools=enable_tools,
        preferred_tool=preferred_tool,
        allowlist=list(allowlist or []),
    )


async def review(
    user_input: str,
    assistant_reply: str,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    if USE_API:
        return await api_review(user_input, assistant_reply, provider=provider, model=model)
    from app.ai.reviewer import senior_review

    return await senior_review(user_input, assistant_reply, provider=provider, model=model)
