from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.ai.llm.factory import get_provider_and_model
from app.api.schemas import ChatRequest, ChatRequestV2, ChatResponse
from app.api.services import run_chat
from app.core.config import settings
from app.core.exceptions import AuthenticationException, BaseApplicationException

router = APIRouter()
logger = logging.getLogger(__name__)

try:
    from app.api.routes import auth as auth_module

    AUTH_AVAILABLE = True
except ImportError:
    auth_module = None
    AUTH_AVAILABLE = False

IS_DEVELOPMENT = settings.environment == "development"
if IS_DEVELOPMENT:
    logger.warning("Running in development mode; authentication is disabled.")


async def get_optional_user(request: Request) -> Any:
    if IS_DEVELOPMENT:
        auth_header = request.headers.get("authorization", "")
        if not auth_header:
            return SimpleNamespace(
                email="dev@example.com",
                roles=["admin", "user"],
                subscription_id="12345678-1234-1234-1234-123456789012",
                is_active=True,
            )
    if AUTH_AVAILABLE and auth_module is not None:
        token_data = await auth_module.auth_required(request)
        return SimpleNamespace(
            email=token_data.email,
            roles=token_data.roles,
            subscription_id=token_data.subscription_id,
            is_active=True,
        )
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        raise AuthenticationException("Authentication required")
    return SimpleNamespace(email="token-user", roles=["user"], subscription_id=None, is_active=True)


@router.post("")
async def chat(
    req: ChatRequest,
    stream: Annotated[bool, Query(False)],
    current_user: Annotated[Any, Depends(get_optional_user)],
) -> StreamingResponse | dict[str, Any]:
    if stream and not req.enable_tools:
        return StreamingResponse(
            _stream_plain_chat(req, current_user),
            media_type="text/event-stream",
        )
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
        return ChatResponse(output=text).model_dump()
    except BaseApplicationException as exc:
        msg = exc.user_message or "Failed to process request."
        return ChatResponse(output=msg).model_dump()
    except Exception:
        return ChatResponse(output="Failed to process request.").model_dump()


@router.post("/v2")
async def chat_v2(
    body: ChatRequestV2,
    current_user: Annotated[Any, Depends(get_optional_user)],
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
    try:
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
                yield f"data: {text[i : i + chunk]}\n\n".encode()
                await asyncio.sleep(0)
            yield b"data: [DONE]\n\n"
            return
        memory = [m.model_dump() for m in req.memory or []]
        messages = [{"role": m["role"], "content": m["content"]} for m in memory]
        messages.append({"role": "user", "content": req.input})
        async for token in llm.chat_stream(model=model, messages=messages):
            if token:
                yield f"data: {token}\n\n".encode()
                await asyncio.sleep(0)
        yield b"data: [DONE]\n\n"
    except BaseApplicationException as exc:
        msg = exc.user_message or "Failed to process request."
        yield f"data: {msg}\n\n".encode()
        yield b"data: [DONE]\n\n"
    except Exception:
        yield b"data: Failed to process request.\n\n"
        yield b"data: [DONE]\n\n"
