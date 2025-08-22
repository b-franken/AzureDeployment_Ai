from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.schemas import ReviewRequest, ReviewResponse
from app.api.services import run_review
from app.core.exceptions import AuthenticationException

router = APIRouter()

IS_DEVELOPMENT = os.getenv("ENVIRONMENT", "development") == "development"


async def get_optional_auth(request: Request) -> dict[str, Any] | None:
    if IS_DEVELOPMENT:
        return {"user": "dev"}
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        raise AuthenticationException("Authentication required")
    return {"user": "authenticated"}


@router.post("", response_model=ReviewResponse)
async def review(
    req: ReviewRequest, auth: dict[str, Any] | None = Depends(get_optional_auth)
) -> dict:
    text = await run_review(
        req.user_input,
        req.assistant_reply,
        req.provider,
        req.model,
    )
    return ReviewResponse(output=text).model_dump()
