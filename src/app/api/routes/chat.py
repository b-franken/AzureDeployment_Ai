from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.schemas import ChatRequest, ChatResponse
from app.api.services import run_chat

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, stream: bool = Query(default=False)) -> Response:
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
