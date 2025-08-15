from __future__ import annotations

from collections.abc import Sequence

from app.ai.reviewer import senior_review
from app.ai.tools_router import maybe_call_tool


async def run_chat(
    input_text: str,
    memory: Sequence[dict] | None,
    provider: str | None,
    model: str | None,
    enable_tools: bool,
    preferred_tool: str | None,
    allowlist: Sequence[str] | None,
) -> str:
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


async def run_review(
    user_input: str,
    assistant_reply: str,
    provider: str | None,
    model: str | None,
) -> str:
    return await senior_review(
        user_input,
        assistant_reply,
        provider=provider,
        model=model,
    )
