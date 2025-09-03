from __future__ import annotations

import uuid
from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.tools.azure.deployment.state_machine import (
    DeploymentContext,
    DeploymentState,
    DeploymentStateMachine,
)

logger = get_logger(__name__)


_PENDING_DEPLOYMENTS: dict[str, dict[str, Any]] = {}


async def _get_redis_client() -> redis.Redis | None:
    """Get Redis client for deployment state storage."""
    try:
        settings = get_settings()
        if hasattr(settings, "redis") and settings.redis.url:
            client: redis.Redis = redis.from_url(  # type: ignore[no-untyped-call]
                settings.redis.url, decode_responses=True
            )
            return client
    except Exception as e:
        logger.warning(f"Could not connect to Redis: {e}")
    return None


async def confirm_deployment(
    clients: Any = None, tags: dict[str, str] | None = None, **kwargs: Any
) -> tuple[str, dict[str, Any]]:
    """
    Confirm and proceed with a pending deployment.
    """
    deployment_id = kwargs.get("deployment_id")

    if not deployment_id:
        recent_deployments = [
            (k, v)
            for k, v in _PENDING_DEPLOYMENTS.items()
            if v.get("status") == "pending_confirmation"
        ]
        if recent_deployments:
            deployment_id = max(recent_deployments, key=lambda x: x[1].get("created_at", ""))[0]

    if not deployment_id or deployment_id not in _PENDING_DEPLOYMENTS:
        return "error", {
            "error": "No pending deployment found",
            "message": "Please create a deployment plan first by requesting to create resources",
            "available_commands": [
                "create resource group test-123 in westeurope",
                "create storage account mydata in westeurope",
            ],
        }

    deployment_plan = _PENDING_DEPLOYMENTS[deployment_id]

    try:
        redis_client = await _get_redis_client()
        state_machine = DeploymentStateMachine(redis_client)

        context = DeploymentContext(
            deployment_id=deployment_id,
            subscription_id=deployment_plan.get("subscription_id", ""),
            resource_group=deployment_plan.get("resource_group", ""),
            location=deployment_plan.get("location", "westeurope"),
            environment=deployment_plan.get("environment", "dev"),
            initiated_by=deployment_plan.get("initiated_by", "user"),
            resources=deployment_plan.get("resources", []),
            dry_run=False,  # This is the actual execution
            metadata=deployment_plan.get("metadata", {}),
        )

        logger.info(f"Starting deployment execution for {deployment_id}")

        result_context = await state_machine.execute(context)

        _PENDING_DEPLOYMENTS.pop(deployment_id, None)

        if result_context.state == DeploymentState.COMPLETED:
            return "created", {
                "deployment_id": deployment_id,
                "status": "completed",
                "resources_deployed": len(result_context.deployed_resources),
                "deployed_resources": result_context.deployed_resources,
                "duration": "estimated",
                "next_steps": [
                    "Resources have been successfully deployed",
                    "You can now use the Azure portal to manage these resources",
                    "Consider setting up monitoring and alerts",
                ],
            }
        if result_context.state == DeploymentState.FAILED:
            return "failed", {
                "deployment_id": deployment_id,
                "status": "failed",
                "error": result_context.error_details,
                "next_steps": [
                    "Review the error details above",
                    "Fix any issues and try again",
                    "Contact support if the issue persists",
                ],
            }
        return "in_progress", {
            "deployment_id": deployment_id,
            "status": result_context.state.value,
            "progress": f"State: {result_context.state.value}",
            "checkpoints": result_context.checkpoints,
        }

    except Exception as e:
        logger.error(f"Deployment execution failed: {e}")
        return "failed", {
            "deployment_id": deployment_id,
            "error": str(e),
            "message": "Deployment execution failed due to an unexpected error",
        }


async def execute_deployment(
    clients: Any = None, tags: dict[str, str] | None = None, **kwargs: Any
) -> tuple[str, dict[str, Any]]:
    """
    Alias for confirm_deployment - execute a pending deployment.
    """
    return await confirm_deployment(clients, tags, **kwargs)


async def cancel_deployment(
    clients: Any = None, tags: dict[str, str] | None = None, **kwargs: Any
) -> tuple[str, dict[str, Any]]:
    """
    Cancel a pending deployment.
    """
    deployment_id = kwargs.get("deployment_id")

    if not deployment_id:
        recent_deployments = [
            (k, v)
            for k, v in _PENDING_DEPLOYMENTS.items()
            if v.get("status") == "pending_confirmation"
        ]
        if recent_deployments:
            deployment_id = max(recent_deployments, key=lambda x: x[1].get("created_at", ""))[0]

    if not deployment_id or deployment_id not in _PENDING_DEPLOYMENTS:
        return "error", {
            "error": "No pending deployment found",
            "message": "There are no pending deployments to cancel",
        }

    deployment_plan = _PENDING_DEPLOYMENTS.pop(deployment_id, None)

    return "cancelled", {
        "deployment_id": deployment_id,
        "status": "cancelled",
        "message": "Deployment has been cancelled",
        "cancelled_resources": deployment_plan.get("resources", []) if deployment_plan else [],
    }


def store_pending_deployment(deployment_id: str, deployment_data: dict[str, Any]) -> None:
    """
    Store a pending deployment for later confirmation.
    """
    deployment_data["created_at"] = str(uuid.uuid4())  # Simple timestamp substitute
    deployment_data["status"] = "pending_confirmation"
    _PENDING_DEPLOYMENTS[deployment_id] = deployment_data
    logger.info(
        f"Stored pending deployment {deployment_id} with "
        f"{len(deployment_data.get('resources', []))} resources"
    )


def get_pending_deployment(deployment_id: str) -> dict[str, Any] | None:
    """
    Get a pending deployment by ID.
    """
    return _PENDING_DEPLOYMENTS.get(deployment_id)


def list_pending_deployments() -> list[dict[str, Any]]:
    """
    List all pending deployments.
    """
    return [
        {"deployment_id": k, **v}
        for k, v in _PENDING_DEPLOYMENTS.items()
        if v.get("status") == "pending_confirmation"
    ]
