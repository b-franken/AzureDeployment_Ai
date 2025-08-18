from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.ai.tools_router import ToolExecutionContext, maybe_call_tool
from app.api.routes.auth import TokenData, require_role
from app.api.schemas import DeploymentRequest
from app.common.envs import normalize_env

router = APIRouter()
deploy_role_dependency = require_role("deploy")


@router.post("")
async def deploy(
    req: DeploymentRequest,
    td: Annotated[TokenData, Depends(deploy_role_dependency)],
) -> dict[str, Any]:
    if req.environment == "production" and "admin" not in td.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin required for production",
        )
    start = time.time()
    canon_env = normalize_env(req.environment)
    ctx = ToolExecutionContext(
        user_id=td.user_id,
        subscription_id=req.subscription_id,
        resource_group=req.resource_group,
        environment=canon_env,
        correlation_id=req.correlation_id,
        cost_limit=int(req.cost_limit) if req.cost_limit is not None else None,
        dry_run=req.dry_run,
    )
    out = await maybe_call_tool(
        user_input=req.request,
        memory=[
            {"role": "system", "content": f"subscription:{req.subscription_id}"},
            {"role": "system", "content": f"environment:{canon_env}"},
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
        "environment": canon_env,
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
