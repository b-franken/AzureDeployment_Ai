from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from app.ai.reviewer import senior_review
from app.ai.tools_router import ToolExecutionContext, maybe_call_tool
from app.core.config import settings

# Global cache for capturing rich tool outputs when orchestrator fails
_rich_output_cache: dict[str, str] = {}

def cache_rich_output(correlation_id: str, output: str) -> None:
    """Cache rich tool output for potential use if orchestrator returns generic response."""
    if correlation_id and ("## Bicep Infrastructure Code" in output or "## Terraform Infrastructure Code" in output):
        _rich_output_cache[correlation_id] = output
        logger.info(f"Cached rich output for correlation {correlation_id}")

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
    dry_run: bool = True,
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
            dry_run=bool(dry_run),
            max_tool_executions=5,
        )
        if enable_tools
        else None
    )
    if context:
        logger.info(
            f"Created tool execution context: correlation_id={context.correlation_id}, max_executions={context.max_tool_executions}, subscription_id={context.subscription_id}"
        )
    result = await maybe_call_tool(
        input_text,
        mem,
        provider=provider,
        model=model,
        enable_tools=enable_tools,
        preferred_tool=preferred_tool,
        allowlist=list(allowlist or []),
        context=context,
    )
    
    # Check if we got a generic response when tools were enabled and the input suggests deployment
    if (enable_tools and 
        isinstance(result, str) and 
        ("Please hold on for a moment" in result or "I'll create" in result or "I'll proceed" in result) and
        len(result) < 300 and
        ("create" in input_text.lower() and ("resource" in input_text.lower() or "deploy" in input_text.lower()))):
        
        logger.warning(f"Detected generic response '{result[:100]}...' for deployment request - this suggests orchestrator issue")
        
        # Check multiple sources for rich output
        correlation_id = correlation_id or (context.correlation_id if context else None)
        
        # First try context cache
        if context and hasattr(context, 'last_tool_output') and context.last_tool_output:
            logger.info("Using cached tool output from context instead of generic response")
            return context.last_tool_output
            
        # Then try global cache by correlation ID
        if correlation_id and correlation_id in _rich_output_cache:
            logger.info(f"Using cached rich output for correlation {correlation_id} instead of generic response")
            cached_output = _rich_output_cache.pop(correlation_id)  # Remove after use
            return cached_output
    
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
