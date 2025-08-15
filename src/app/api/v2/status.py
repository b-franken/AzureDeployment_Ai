from __future__ import annotations

import os

from fastapi import APIRouter

router = APIRouter()


@router.get("/status")
async def status() -> dict:
    return {
        "version": os.getenv("APP_VERSION", "2.0.0"),
        "environment": "production",
        "features": {
            "ai_chat": True,
            "azure_provisioning": True,
            "cost_management": True,
            "audit_logging": True,
            "multi_cloud": False,
        },
        "limits": {
            "chat_requests_per_minute": 30,
            "deployment_requests_per_minute": 10,
            "max_request_size_mb": 10,
        },
    }
