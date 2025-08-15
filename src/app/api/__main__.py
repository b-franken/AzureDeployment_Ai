from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from app.api.routes.chat import router as chat_router
from app.api.routes.healthz import router as healthz_router
from app.api.routes.review import router as review_router
from app.api.v2 import router as v2_router

app = FastAPI()
app.include_router(healthz_router)
app.include_router(chat_router)
app.include_router(review_router)
app.include_router(v2_router, prefix="/api/v2")


def main() -> None:
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run(
        "app.api.main:app", host=host, port=port, reload=os.getenv("API_RELOAD", "0") == "1"
    )


if __name__ == "__main__":
    main()
