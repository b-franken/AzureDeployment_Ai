from __future__ import annotations
from fastapi import HTTPException

from datetime import datetime
from app.core.config import get_settings
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"api": "healthy", "timestamp": datetime.utcnow().isoformat()}


@router.get("/health/llm")
async def health_llm() -> dict:
    s = get_settings()
    ok = bool(s.llm.openai_api_key)
    if not ok:
        raise HTTPException(
            status_code=500, detail="OPENAI_API_KEY not configured")
    return {"llm": "ready"}
