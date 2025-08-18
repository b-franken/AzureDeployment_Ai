from __future__ import annotations

from .audit import router as audit_router
from .auth import router as auth_router
from .chat import router as chat_router
from .cost import router as cost_router
from .deploy import router as deploy_router
from .health import router as health_router
from .metrics import router as metrics_router
from .review import router as review_router
from .status import router as status_router

__all__ = [
    "audit_router",
    "auth_router",
    "chat_router",
    "cost_router",
    "deploy_router",
    "health_router",
    "metrics_router",
    "review_router",
    "status_router",
]
