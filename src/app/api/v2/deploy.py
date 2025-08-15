from __future__ import annotations

import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.ai.tools_router import ToolExecutionContext, maybe_call_tool
from app.api.v2.auth import require_role, token_data

router = APIRouter()
deploy_role_dependency = require_role("deploy")


class deployment_request(BaseModel):
    request: str = Field(min_length=1, max_length=5000)
    subscription_id: str
    resource_group: str | None = None
    environment: str = "development"
    dry_run: bool = True
    cost_limit: float | None = Field(default=None, ge=0)
    tags: dict[str, str] = Field(default_factory=dict)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


@router.post("/deploy")
async def deploy(
    req: deployment_request,
    td: Annotated[token_data, Depends(deploy_role_dependency)],
) -> dict[str, Any]:
    if req.environment == "production" and "admin" not in td.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin required for production",
        )
    start = time.time()
    ctx = ToolExecutionContext(
        user_id=td.user_id,
        subscription_id=req.subscription_id,
        resource_group=req.resource_group,
        environment=(
            "prod"
            if req.environment == "production"
            else "dev" if req.environment == "development" else "acc"
        ),
        correlation_id=req.correlation_id,
        cost_limit=int(req.cost_limit) if req.cost_limit is not None else None,
        dry_run=req.dry_run,
    )
    out = await maybe_call_tool(
        user_input=req.request,
        memory=[
            {"role": "system", "content": f"subscription:{req.subscription_id}"},
            {"role": "system", "content": f"environment:{req.environment}"},
            {"role": "system", "content": f"dry_run:{req.dry_run}"},
        ],
        provider="openai",
        model=None,
        enable_tools=True,
        allowlist=["provision_orchestrator"],
        preferred_tool="provision_orchestrator",
        context=ctx,
        return_json=True,
    )
    took = time.time() - start
    return {
        "status": "accepted",
        "environment": req.environment,
        "dry_run": req.dry_run,
        "details": {
            "request": req.request,
            "subscription_id": req.subscription_id,
            "resource_group": req.resource_group,
            "cost_limit": req.cost_limit,
            "tags": dict(req.tags),
        },
        "response": out,
        "correlation_id": req.correlation_id,
        "processing_time": took,
    }
