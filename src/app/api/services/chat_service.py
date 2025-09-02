from __future__ import annotations

import logging

from app.core.logging import get_logger
import uuid
from collections.abc import Sequence
from typing import Any, Literal, cast

from app.ai.reviewer import senior_review
from app.ai.tools_router import ToolExecutionContext, maybe_call_tool
from app.api.services.memory_service import get_memory_service
from app.core.config import settings

# Global cache for capturing rich tool outputs when orchestrator fails
_rich_output_cache: dict[str, str] = {}


def cache_rich_output(correlation_id: str, output: str) -> None:
    """Cache rich tool output for potential use if orchestrator returns generic response."""
    if correlation_id and (
        "## Bicep Infrastructure Code" in output or "## Terraform Infrastructure Code" in output
    ):
        _rich_output_cache[correlation_id] = output
        logger.info(f"Cached rich output for correlation {correlation_id}")


logger = get_logger(__name__)


async def run_chat(
    input_text: str,
    memory: Sequence[dict[str, Any]] | None,
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
    dry_run: bool = True,
    store_conversation: bool = True,
    thread_id: str | None = None,
) -> str:
    memory_service = get_memory_service()
    effective_correlation_id = correlation_id or str(uuid.uuid4())

    # Retrieve user's conversation history if no memory provided and store_conversation is enabled
    if store_conversation and (not memory or len(memory) == 0):
        try:
            historical_memory = await memory_service.get_user_conversation_history(
                user_id=user_id,
                limit=10,  # Last 10 messages for context
                thread_id=thread_id,
            )
            mem = list(historical_memory)
            logger.info(f"Retrieved {len(mem)} messages from user memory for context")
        except Exception as exc:
            logger.warning(f"Failed to retrieve user memory, using provided memory: {exc}")
            mem = list(memory or [])
    else:
        mem = list(memory or [])

    # Store user message if conversation storage is enabled
    user_message_id = None
    if store_conversation:
        try:
            user_message_id = await memory_service.store_user_message(
                user_id=user_id,
                content=input_text,
                thread_id=thread_id,
                session_id=effective_correlation_id,
                metadata={
                    "provider": provider,
                    "model": model,
                    "tools_enabled": enable_tools,
                    "environment": environment,
                },
            )
            logger.info(f"Stored user message with ID: {user_message_id}")
        except Exception as exc:
            logger.error(f"Failed to store user message: {exc}")

    effective_subscription_id = subscription_id or settings.azure.subscription_id
    context = (
        ToolExecutionContext(
            user_id=user_id,
            correlation_id=effective_correlation_id,
            subscription_id=effective_subscription_id,
            resource_group=resource_group,
            environment=cast(
                Literal["dev", "tst", "acc", "prod"],
                "dev" if environment not in ["dev", "tst", "acc", "prod"] else environment,
            ),
            audit_enabled=True,
            dry_run=bool(dry_run),
            max_tool_executions=5,
        )
        if enable_tools
        else None
    )
    if context:
        logger.info(
            f"Created tool execution context: correlation_id={context.correlation_id}, "
            f"max_executions={context.max_tool_executions}, "
            f"subscription_id={context.subscription_id}"
        )

    # Track tools that will be used for metadata
    tools_used: list[str] = []

    result = await maybe_call_tool(
        input_text,
        mem,
        provider=provider,
        model=model,
        enable_tools=enable_tools,
        preferred_tool=preferred_tool,
        allowlist=list(allowlist or []),
        context=context,
        conversation_context=(
            [{"role": msg["role"], "content": msg["content"]} for msg in mem] if mem else None
        ),
    )

    # Extract tool usage information if available from context
    if context and hasattr(context, "executed_tools"):
        tools_used = list(context.executed_tools) if context.executed_tools else []
    elif enable_tools and "azure" in result.lower() and "deploy" in result.lower():
        tools_used = ["azure_provision"]  # Infer tool usage from response content

    # Check if we got a generic response when tools were enabled and the input suggests deployment
    if (
        enable_tools
        and isinstance(result, str)
        and (
            "Please hold on for a moment" in result
            or "I'll create" in result
            or "I'll proceed" in result
        )
        and len(result) < 300
        and (
            "create" in input_text.lower()
            and ("resource" in input_text.lower() or "deploy" in input_text.lower())
        )
    ):
        logger.warning(
            f"Detected generic response '{result[:100]}...' for deployment request - "
            "this suggests orchestrator issue"
        )

        # Check multiple sources for rich output
        correlation_id = correlation_id or (context.correlation_id if context else None)

        # First try context cache
        if context and hasattr(context, "last_tool_output") and context.last_tool_output:
            logger.info("Using cached tool output from context instead of generic response")
            return context.last_tool_output

        # Then try global cache by correlation ID
        if correlation_id and correlation_id in _rich_output_cache:
            logger.info(
                f"Using cached rich output for correlation {correlation_id} "
                "instead of generic response"
            )
            cached_output = _rich_output_cache.pop(correlation_id)  # Remove after use
            return cached_output

    # Store assistant response if conversation storage is enabled
    if store_conversation:
        try:
            assistant_message_id = await memory_service.store_assistant_message(
                user_id=user_id,
                content=result,
                thread_id=thread_id,
                session_id=effective_correlation_id,
                model_info={"provider": provider, "model": model},
                tools_used=tools_used,
                metadata={
                    "user_message_id": user_message_id,
                    "response_length": len(result),
                    "tools_enabled": enable_tools,
                    "environment": environment,
                },
            )
            logger.info(f"Stored assistant response with ID: {assistant_message_id}")
        except Exception as exc:
            logger.error(f"Failed to store assistant response: {exc}")

    return result


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
