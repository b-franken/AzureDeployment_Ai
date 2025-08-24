from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.ai.tools_router import ToolExecutionContext, maybe_call_tool
from app.api.routes.auth import TokenData, require_role
from app.api.schemas import DeploymentRequest
from app.common.envs import normalize_env
from app.core.logging import get_logger
from app.events.provisioning_task import run_provisioning
from app.platform.audit.logger import (
    AuditEvent,
    AuditEventType,
    AuditLogger,
    AuditSeverity,
)

router = APIRouter()
deploy_role_dependency = require_role("deploy")
logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


@router.post("/start")
async def start_deploy(td: Annotated[TokenData, Depends(deploy_role_dependency)]) -> dict[str, str]:
    deployment_id = str(uuid4())
    with tracer.start_as_current_span("deploy.start") as span:
        span.set_attribute("user.id", td.user_id)
        span.set_attribute("deployment.id", deployment_id)
        asyncio.create_task(run_provisioning(deployment_id), name=f"provision:{deployment_id}")
        logger.info("deploy_background_started", user_id=td.user_id, deployment_id=deployment_id)
    try:
        audit = AuditLogger()
        await audit.initialize()
        await audit.log_event(
            AuditEvent(
                event_type=AuditEventType.DEPLOYMENT_STARTED,
                severity=AuditSeverity.INFO,
                user_id=td.user_id,
                correlation_id=deployment_id,
                action="background_provisioning_start",
            )
        )
    except Exception:
        logger.warning("audit_log_failed_start", deployment_id=deployment_id, exc_info=True)
    return {"deployment_id": deployment_id}


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
    try:
        canon_env = normalize_env(req.environment)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    start = perf_counter()
    audit = AuditLogger()
    await audit.initialize()
    ctx = ToolExecutionContext(
        user_id=td.user_id,
        subscription_id=req.subscription_id,
        resource_group=req.resource_group,
        environment=canon_env,
        correlation_id=req.correlation_id,
        cost_limit=int(req.cost_limit) if req.cost_limit is not None else None,
        dry_run=req.dry_run,
        audit_logger=audit,
    )
    with tracer.start_as_current_span("deploy.execute") as span:
        span.set_attribute("user.id", td.user_id)
        span.set_attribute("subscription.id", req.subscription_id or "")
        span.set_attribute("resource.group", req.resource_group or "")
        span.set_attribute("environment", canon_env)
        span.set_attribute("dry_run", bool(req.dry_run))
        try:
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
            took = perf_counter() - start
            resp: dict[str, Any] = {
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
            logger.info(
                "deploy_request_ok",
                user_id=td.user_id,
                environment=canon_env,
                dry_run=req.dry_run,
                correlation_id=req.correlation_id,
                took_ms=round(took * 1000, 2),
            )
            try:
                await audit.log_event(
                    AuditEvent(
                        event_type=AuditEventType.DEPLOYMENT_COMPLETED,
                        severity=AuditSeverity.INFO,
                        user_id=td.user_id,
                        subscription_id=req.subscription_id,
                        resource_group=req.resource_group,
                        correlation_id=req.correlation_id,
                        action="deploy_execute",
                        result="success",
                        details={"dry_run": req.dry_run, "environment": canon_env},
                    )
                )
            except Exception:
                logger.warning(
                    "audit_log_failed_complete", correlation_id=req.correlation_id, exc_info=True
                )
            return resp
        except HTTPException:
            span.set_status(Status(StatusCode.ERROR))
            raise
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(
                "deploy_request_failed",
                user_id=td.user_id,
                environment=canon_env,
                correlation_id=req.correlation_id,
                exc_info=True,
            )
            try:
                await audit.log_event(
                    AuditEvent(
                        event_type=AuditEventType.DEPLOYMENT_FAILED,
                        severity=AuditSeverity.ERROR,
                        user_id=td.user_id,
                        subscription_id=req.subscription_id,
                        resource_group=req.resource_group,
                        correlation_id=req.correlation_id,
                        action="deploy_execute",
                        result="failed",
                        details={"error": str(e)},
                    )
                )
            except Exception:
                logger.warning(
                    "audit_log_failed_error", correlation_id=req.correlation_id, exc_info=True
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="deployment_failed"
            ) from e
