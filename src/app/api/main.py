from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.chat import router as chat_router
from app.api.routes.review import router as review_router
from app.api.v2 import router as v2_router

APP_VERSION = os.getenv("APP_VERSION", "2.0.0")
app = FastAPI(title="DevOps AI API", version=APP_VERSION)


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


app.include_router(chat_router, prefix="/api")
app.include_router(review_router, prefix="/api")


app.include_router(v2_router, prefix="/api/v2")


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}
