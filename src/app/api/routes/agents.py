from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.ai.agents.provisioning import ProvisioningAgent, ProvisioningAgentConfig
from app.ai.agents.types import AgentContext
from app.ai.tools_router import ToolExecutionContext
from app.api.routes.auth import TokenData, require_role
from app.core.logging import get_logger

logger = get_logger(__name__)
# Store references to background tasks for optional introspection/cancellation
_background_tasks: set[asyncio.Task[Any]] = set()


def _log_task_result(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except Exception:
        logger.exception("Provisioning task failed")
    finally:
        _background_tasks.discard(task)


router = APIRouter()
deploy_role_dependency = require_role("deploy")


class ProvisionRequest(BaseModel):
    goal: str = Field(min_length=1)
    provider: str | None = None
    model: str | None = None


@router.post("/provision")
async def provision(
    req: ProvisionRequest, td: Annotated[TokenData, Depends(deploy_role_dependency)]
) -> dict[str, Any]:
    ctx = ToolExecutionContext(user_id=td.user_id, subscription_id=td.subscription_id)

    # Convert ToolExecutionContext to AgentContext
    agent_context = AgentContext(
        user_id=ctx.user_id,
        subscription_id=ctx.subscription_id,
        resource_group=ctx.resource_group,
        environment=ctx.environment,
        correlation_id=ctx.correlation_id,
        dry_run=ctx.dry_run,
    )

    agent = ProvisioningAgent(
        user_id=td.user_id,
        context=agent_context,
        config=ProvisioningAgentConfig(provider=req.provider, model=req.model),
    )
    plan = await agent.plan(req.goal)
    # Agent.run expects a goal string, not a plan object
    task = asyncio.create_task(agent.run(req.goal))
    _background_tasks.add(task)
    task.add_done_callback(_log_task_result)
    return {"status": "accepted", "deployment_id": plan.steps[0].name if plan.steps else "ad-hoc"}
