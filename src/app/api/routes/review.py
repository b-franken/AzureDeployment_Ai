from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.schemas import ReviewRequest, ReviewResponse
from app.api.services import run_review

router = APIRouter()

IS_DEVELOPMENT = os.getenv("ENVIRONMENT", "development") == "development"


async def get_optional_auth(request: Request) -> dict | None:
    """Optional authentication for development"""
    if IS_DEVELOPMENT:
        return {"user": "dev"}

    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"user": "authenticated"}


@router.post("", response_model=ReviewResponse)
async def review(
    req: ReviewRequest, auth: dict | None = Depends(get_optional_auth)
) -> JSONResponse:
    """Review endpoint - authentication optional in development"""
    try:
        text = await run_review(
            req.user_input,
            req.assistant_reply,
            req.provider,
            req.model,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse(ReviewResponse(output=text).model_dump())
