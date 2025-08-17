from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.middleware.rate_limiter import RateLimitConfig, RateLimiter
from app.api.routes.chat import router as chat_router
from app.api.routes.review import router as review_router
from app.api.v2 import router as v2_router
from app.observability.prometheus import instrument_app

import inspect
print("MAIN FILE:", __file__)

APP_VERSION = os.getenv("APP_VERSION", "2.0.0")
app = FastAPI(title="DevOps AI API", version=APP_VERSION)
instrument_app(app)


@app.get("/_routes")
def _routes():
    return [r.path for r in app.routes]


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


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
)

limiter = RateLimiter(RateLimitConfig(
    requests_per_minute=30, requests_per_hour=1000))


@app.middleware("http")
async def _rl_mw(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    try:
        await limiter.check_rate_limit(request)
        return await call_next(request)
    except HTTPException:
        raise
    except Exception:
        raise


app.include_router(chat_router, prefix="/api")
app.include_router(review_router, prefix="/api")
app.include_router(v2_router, prefix="/api/v2")


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}
