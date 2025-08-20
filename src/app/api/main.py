from __future__ import annotations

import os
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from starlette.routing import Mount, Route, WebSocketRoute

from app.api.error_handlers import install_error_handlers
from app.api.middleware.authentication import install_auth_middleware
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
from app.core.logging import get_logger
from app.observability.app_insights import app_insights
from app.observability.prometheus import instrument_app
from app.api.routes.ws import router as ws_router
from app.api.routes.agents import router as agents_router


logger = get_logger(__name__)

env_is_dev = settings.environment == "development"

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
        redis_max_connections=settings.database.redis_max_connections,
        redis_socket_timeout=float(settings.database.redis_socket_timeout),
    )
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API starting up", version=settings.app_version,
                environment=settings.environment)
    app_insights.initialize()
    yield
    rb = limiter.redis_backend
    if rb and rb._client:
        await rb._client.aclose()
    logger.info("API shutting down")


app = FastAPI(
    title="DevOps AI API",
    version=settings.app_version,
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    lifespan=lifespan,
)

instrument_app(app)

origins = [str(o) for o in settings.security.allowed_cors_origins] or ["*"]
allow_credentials = False if origins == ["*"] else True

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-correlation-id"],
)

install_error_handlers(app)
install_correlation_middleware(app)
install_telemetry_middleware(app)
install_auth_middleware(app)


@app.middleware("http")
async def _rl_mw(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    user_id = getattr(request.state, "user_id", None)
    await limiter.check_rate_limit(request, user_id)
    return await call_next(request)


@app.get("/_routes")
def _routes() -> list[str]:
    return [r.path for r in app.routes if isinstance(r, (APIRoute, Route, Mount, WebSocketRoute))]


app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
app.include_router(review_router, prefix="/api/review", tags=["review"])
app.include_router(deploy_router, prefix="/api/deploy", tags=["deploy"])
app.include_router(cost_router, prefix="/api/cost", tags=["cost"])
app.include_router(audit_router, prefix="/api/audit", tags=["audit"])
app.include_router(metrics_router, prefix="/api/metrics", tags=["metrics"])
app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(status_router, prefix="/api", tags=["status"])
app.include_router(agents_router, prefix="/api/agents", tags=["agents"])
app.include_router(ws_router, tags=["ws"])
