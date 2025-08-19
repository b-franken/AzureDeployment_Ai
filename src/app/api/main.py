from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from starlette.routing import Mount, Route, WebSocketRoute

from app.api.error_handlers import install_error_handlers
from app.api.middleware.correlation import install_correlation_middleware
from app.api.middleware.rate_limiter import RateLimitConfig, RateLimiter
from app.api.middleware.telemetry import install_telemetry_middleware
from app.api.routes.audit import router as audit_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.cost import router as cost_router
from app.api.routes.deploy import router as deploy_router
from app.api.routes.health import router as health_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.review import router as review_router
from app.api.routes.status import router as status_router
from app.core.config import settings
from src.app.core.loging import get_logger
from app.observability.app_insights import app_insights
from app.observability.prometheus import instrument_app

logger = get_logger(__name__)

env_is_dev = settings.environment == "development"

APP_VERSION = os.getenv("APP_VERSION", "2.0.0")
app = FastAPI(
    title="DevOps AI API",
    version=APP_VERSION,
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
)

app_insights.initialize()
instrument_app(app)

install_error_handlers(app)

origins_raw = os.getenv("CORS_ORIGINS", "*").strip()
if origins_raw in {"", "*"}:
    allow_origins = ["*"]
    allow_credentials = False
else:
    allow_origins = [o.strip() for o in origins_raw.split(",") if o.strip()]
    allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-correlation-id"],
)

install_correlation_middleware(app)
install_telemetry_middleware(app)

limiter = RateLimiter(
    RateLimitConfig(
        requests_per_minute=settings.security.api_rate_limit_per_minute,
        requests_per_hour=settings.security.api_rate_limit_per_hour,
        burst_size=10,
        enable_ip_tracking=True,
        enable_user_tracking=True,
        redis_url=(
            str(settings.database.redis_dsn)
            if (settings.database.redis_dsn or not env_is_dev)
            else None
        ),
    )
)


@app.middleware("http")
async def _rl_mw(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    await limiter.check_rate_limit(request)
    return await call_next(request)


@app.on_event("startup")
async def startup_event() -> None:
    logger.info(
        "API starting up",
        version=APP_VERSION,
        environment=settings.environment,
        entra_id_enabled=os.getenv("USE_ENTRA_ID", "false").lower() in {
            "true", "1", "yes"},
    )


@app.on_event("shutdown")
async def shutdown_event() -> None:
    logger.info("API shutting down")


@app.get("/_routes")
def _routes() -> list[str]:
    return [r.path for r in app.routes if isinstance(r, APIRoute | Route | Mount | WebSocketRoute)]


app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
app.include_router(review_router, prefix="/api/review", tags=["review"])
app.include_router(deploy_router, prefix="/api/deploy", tags=["deploy"])
app.include_router(cost_router, prefix="/api/cost", tags=["cost"])
app.include_router(audit_router, prefix="/api/audit", tags=["audit"])
app.include_router(metrics_router, prefix="/api/metrics", tags=["metrics"])
app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(status_router, prefix="/api", tags=["status"])
