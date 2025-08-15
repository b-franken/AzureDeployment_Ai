from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.ai.tools_router import maybe_call_tool
from app.api.v2.auth import auth_required

router = APIRouter()


class chat_request(BaseModel):
    input: str = Field(min_length=1, max_length=5000)
    memory: list[dict[str, str]] | None = None
    provider: str | None = None
    model: str | None = None
    enable_tools: bool = True
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


@router.post("/chat")
async def chat(request: Request, body: chat_request) -> dict[str, Any]:
    await auth_required(request)
    start = time.time()
    out = await maybe_call_tool(
        user_input=body.input,
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
