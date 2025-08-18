from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.routes.auth import auth_dependency
from app.api.schemas import ChatRequest, ChatRequestV2, ChatResponse, TokenData
from app.api.services import run_chat

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=ChatResponse)
async def chat(
    request: Request,
    req: ChatRequest,
    stream: bool = Query(default=False),
    td: Annotated[TokenData, Depends(auth_dependency)] = None,
) -> Response:
    try:
        text = await run_chat(
            req.input,
            [m.model_dump() for m in req.memory or []],
            req.provider,
            req.model,
            req.enable_tools,
            req.preferred_tool,
            req.allowlist,
        )
    except Exception as exc:
        logger.exception(
            "Chat request failed",
            extra={
                "user_id": getattr(td, "user_id", None),
                "correlation_id": getattr(req, "correlation_id", None)
                or request.headers.get("x-correlation-id"),
            },
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not stream:
        return JSONResponse(ChatResponse(output=text).model_dump())

    async def gen() -> AsyncGenerator[bytes, None]:
        chunk = 2048
        for i in range(0, len(text), chunk):
            part = text[i : i + chunk]
            yield f"data: {part}\n\n".encode()
            await asyncio.sleep(0)
        yield b"data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/v2")
async def chat_v2(
    request: Request, body: ChatRequestV2, td: Annotated[TokenData, Depends(auth_dependency)] = None
) -> dict[str, Any]:
    start = time.time()
    out = await run_chat(
        input_text=body.input,
        memory=body.memory,
        provider=body.provider,
        model=body.model,
        enable_tools=body.enable_tools,
    )
    took = time.time() - start
    return {
        "response": out,
        "correlation_id": body.correlation_id,
        "processing_time": took,
    }
