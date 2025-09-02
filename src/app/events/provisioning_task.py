from __future__ import annotations

from app.ai.agents.provisioning import ProvisioningAgent, ProvisioningAgentConfig
from app.ai.tools_router import ToolExecutionContext


async def run_provisioning(deployment_id: str) -> None:
    """Run a provisioning task asynchronously"""
    from app.ai.agents.types import AgentContext
    from app.core.logging import get_logger
    
    logger = get_logger(__name__)
    
    # Create execution context for the provisioning task
    ctx = ToolExecutionContext(
        user_id="system",
        subscription_id=None,
        environment="dev",
        correlation_id=deployment_id,
    )
    
    # Create agent context from tool execution context
    agent_context = AgentContext(
        user_id=ctx.user_id,
        correlation_id=ctx.correlation_id,
        environment=ctx.environment,
        metadata={"deployment_id": deployment_id}
    )
    
    logger.info(
        "Starting asynchronous provisioning task", 
        deployment_id=deployment_id,
        correlation_id=ctx.correlation_id
    )
    
    agent = ProvisioningAgent(
        user_id=ctx.user_id, 
        context=agent_context, 
        config=ProvisioningAgentConfig()
    )

    await agent.run_provisioning(deployment_id)
