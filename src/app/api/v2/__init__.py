from __future__ import annotations

from fastapi import APIRouter

from app.api.v2.audit import router as audit_router
from app.api.v2.auth import router as auth_router
from app.api.v2.chat import router as chat_router
from app.api.v2.cost import router as cost_router
from app.api.v2.deploy import router as deploy_router
from app.api.v2.health import router as health_router
from app.api.v2.metrics import router as metrics_router

router = APIRouter()
router.include_router(auth_router, prefix="/auth", tags=["v2/auth"])
router.include_router(chat_router, prefix="/chat", tags=["v2/chat"])
router.include_router(deploy_router, prefix="/deploy", tags=["v2/deploy"])
router.include_router(cost_router, prefix="/cost", tags=["v2/cost"])
router.include_router(audit_router, prefix="/audit", tags=["v2/audit"])
router.include_router(metrics_router, prefix="/metrics", tags=["v2/metrics"])
router.include_router(health_router, tags=["v2/health"])
