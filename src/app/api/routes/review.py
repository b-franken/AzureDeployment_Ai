from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.api.schemas import ReviewRequest, ReviewResponse
from app.api.services import run_review

router = APIRouter(prefix="/review", tags=["review"])


@router.post("", response_model=ReviewResponse)
async def review(req: ReviewRequest) -> JSONResponse:
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
