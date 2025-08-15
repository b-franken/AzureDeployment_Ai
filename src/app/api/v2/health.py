from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"api": "healthy", "timestamp": datetime.utcnow().isoformat()}
