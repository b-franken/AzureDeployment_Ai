from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.api.schemas import ReviewRequest, ReviewResponse
from app.api.services import run_review
from app.core.config import settings
from app.core.exceptions import AuthenticationException

router = APIRouter()

IS_DEVELOPMENT = settings.environment == "development"


async def get_optional_auth(request: Request) -> dict[str, Any] | None:
    if IS_DEVELOPMENT:
        return {"user": "dev"}
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        raise AuthenticationException("Authentication required")
    return {"user": "authenticated"}


@router.post("", response_model=ReviewResponse)
async def review(
    req: ReviewRequest,
    _auth: Annotated[dict[str, Any] | None, Depends(get_optional_auth)],
) -> dict[str, Any]:
    text = await run_review(
        req.user_input,
        req.assistant_reply,
        req.provider,
        req.model,
    )
    return ReviewResponse(output=text).model_dump()
