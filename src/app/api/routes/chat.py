from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any, TypeAlias

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.ai.llm.factory import get_provider_and_model
from app.api.schemas import ChatRequest, ChatRequestV2, ChatResponse
from app.api.services import run_chat
from app.core.config import settings
from app.core.exceptions import AuthenticationException

router = APIRouter()
logger = logging.getLogger(__name__)

try:
    from app.api.routes.auth import User, get_current_active_user

    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    User: TypeAlias = Any

    async def get_current_active_user() -> Any:
        return None

IS_DEVELOPMENT = settings.environment == "development"
if IS_DEVELOPMENT:
    logger.warning("Running in development mode; authentication is disabled.")


async def get_optional_user(request: Request) -> Any:
    if IS_DEVELOPMENT:
        auth_header = request.headers.get("authorization", "")
        if not auth_header:
            return type(
                "User",
                (),
                {
                    "email": "dev@example.com",
                    "roles": ["admin", "user"],
                    "subscription_id": "12345678-1234-1234-1234-123456789012",
                    "is_active": True,
                },
            )()
    if AUTH_AVAILABLE:
        return await get_current_active_user()
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        raise AuthenticationException("Authentication required")
    return {"email": "token-user"}


@router.post("", response_model=ChatResponse)
async def chat(
    request: Request,
    req: ChatRequest,
    stream: bool = Query(default=False),
    current_user: Any = Depends(get_optional_user),
) -> dict[str, Any]:
    if stream and not req.enable_tools:
        return StreamingResponse(_stream_plain_chat(req, current_user), media_type="text/event-stream")
    text = await run_chat(
        req.input,
        [m.model_dump() for m in req.memory or []],
        req.provider,
        req.model,
        req.enable_tools,
        req.preferred_tool,
        req.allowlist,
    )
    return ChatResponse(output=text).model_dump()


@router.post("/v2")
async def chat_v2(
    request: Request, body: ChatRequestV2, current_user: Any = Depends(get_optional_user)
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
        "user": getattr(current_user, "email", "anonymous"),
    }


async def _stream_plain_chat(req: ChatRequest, user: Any) -> AsyncGenerator[bytes, None]:
    llm, model = await get_provider_and_model(req.provider, req.model)
    if not hasattr(llm, "chat_stream"):
        text = await run_chat(
            req.input,
            [m.model_dump() for m in req.memory or []],
            req.provider,
            req.model,
            req.enable_tools,
            req.preferred_tool,
            req.allowlist,
        )
        chunk = 2048
        for i in range(0, len(text), chunk):
            yield f"data: {text[i: i + chunk]}\n\n".encode()
            await asyncio.sleep(0)
        yield b"data: [DONE]\n\n"
        return
    memory = [m.model_dump() for m in req.memory or []]
    messages = [{"role": m["role"], "content": m["content"]} for m in memory]
    messages.append({"role": "user", "content": req.input})
    # type: ignore[attr-defined]
    async for token in llm.chat_stream(model=model, messages=messages):
        if token:
            yield f"data: {token}\n\n".encode()
            await asyncio.sleep(0)
    yield b"data: [DONE]\n\n"
