from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.ai.agents.provisioning import ProvisioningAgent, ProvisioningAgentConfig
from app.ai.tools_router import ToolExecutionContext
from app.api.routes.auth import TokenData, require_role

logger = logging.getLogger(__name__)
# Store references to background tasks for optional introspection/cancellation
_background_tasks: set[asyncio.Task] = set()


def _log_task_result(task: asyncio.Task) -> None:
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
    agent = ProvisioningAgent(
        user_id=td.user_id,
        context=ctx,
        config=ProvisioningAgentConfig(provider=req.provider, model=req.model),
    )
    plan = await agent.plan(req.goal)
    task = asyncio.create_task(agent.run(plan))
    _background_tasks.add(task)
    task.add_done_callback(_log_task_result)
    return {"status": "accepted", "deployment_id": plan.steps[0].name if plan.steps else "ad-hoc"}
