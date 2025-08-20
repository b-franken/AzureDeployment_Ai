from __future__ import annotations
import asyncio
from app.ai.agents.provisioning_task import ProvisioningAgent, ProvisioningAgentConfig
from app.ai.tools_router import ToolExecutionContext


async def run_provisioning(deployment_id: str) -> None:
    """Run a provisioning task asynchronously"""
    # Placeholder implementation
    ctx = ToolExecutionContext(
        user_id="system",
        subscription_id=None,
        environment="dev",
        correlation_id=deployment_id,
    )
    agent = ProvisioningAgent(
        user_id="system",
        context=ctx,
        config=ProvisioningAgentConfig()
    )

    await agent.run_provisioning(deployment_id)
