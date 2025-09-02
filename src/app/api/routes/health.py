from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"api": "healthy", "timestamp": datetime.utcnow().isoformat()}


@router.get("/health/llm")
async def health_llm() -> dict[str, str]:
    s = get_settings()
    ok = bool(s.llm.openai_api_key)
    if not ok:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")
    return {"llm": "ready"}
