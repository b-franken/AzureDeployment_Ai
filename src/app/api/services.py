from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from app.ai.reviewer import senior_review
from app.ai.tools_router import ToolExecutionContext, maybe_call_tool
from app.core.config import settings

logger = logging.getLogger(__name__)


async def run_chat(
    input_text: str,
    memory: Sequence[dict] | None,
    provider: str | None,
    model: str | None,
    enable_tools: bool,
    preferred_tool: str | None,
    allowlist: Sequence[str] | None,
    user_id: str = "dev@example.com",
    correlation_id: str | None = None,
    subscription_id: str | None = None,
    resource_group: str | None = None,
    environment: str = "dev",
) -> str:
    mem = list(memory or [])

    effective_subscription_id = subscription_id or settings.azure.subscription_id

    context = (
        ToolExecutionContext(
            user_id=user_id,
            correlation_id=correlation_id or str(uuid.uuid4()),
            subscription_id=effective_subscription_id,
            resource_group=resource_group,
            environment=environment,
            audit_enabled=True,
            dry_run=True,
            max_tool_executions=5,
        )
        if enable_tools
        else None
    )

    if context:
        logger.info(
            f"Created tool execution context: correlation_id={context.correlation_id}, max_executions={context.max_tool_executions}, subscription_id={context.subscription_id}"
        )

    return await maybe_call_tool(
        input_text,
        mem,
        provider=provider,
        model=model,
        enable_tools=enable_tools,
        preferred_tool=preferred_tool,
        allowlist=list(allowlist or []),
        context=context,
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
