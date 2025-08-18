from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/status")
async def status() -> dict:
    return {
        "version": settings.app_version,
        "environment": settings.environment,
        "features": {
            "ai_chat": True,
            "azure_provisioning": True,
            "cost_management": True,
            "audit_logging": settings.security.enable_audit_logging,
            "multi_cloud": False,
        },
        "limits": {
            "chat_requests_per_minute": settings.security.api_rate_limit_per_minute,
            "deployment_requests_per_minute": settings.security.api_rate_limit_per_hour // 100,
            "max_request_size_mb": 10,
        },
    }
