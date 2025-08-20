from __future__ import annotations
import asyncio
from typing import Annotated, Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from app.api.routes.auth import TokenData, require_role
from app.ai.agents.provisioning import ProvisioningAgent, ProvisioningAgentConfig
from app.ai.tools_router import ToolExecutionContext

router = APIRouter()
deploy_role_dependency = require_role("deploy")


class ProvisionRequest(BaseModel):
    goal: str = Field(min_length=1)
    provider: str | None = None
    model: str | None = None


@router.post("/provision")
async def provision(req: ProvisionRequest, td: Annotated[TokenData, Depends(deploy_role_dependency)]) -> dict[str, Any]:
    ctx = ToolExecutionContext(
        user_id=td.user_id, subscription_id=td.subscription_id)
    agent = ProvisioningAgent(user_id=td.user_id, context=ctx, config=ProvisioningAgentConfig(
        provider=req.provider, model=req.model))
    plan = await agent.plan(req.goal)
    asyncio.create_task(agent.run(plan))
    return {"status": "accepted", "deployment_id": plan.steps[0].name if plan.steps else "ad-hoc"}
