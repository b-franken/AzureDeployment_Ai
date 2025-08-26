# src/app/api/routes/chat.py
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.ai.llm.factory import get_provider_and_model
from app.api.schemas import ChatRequest, ChatRequestV2, ChatResponse
from app.api.services import run_chat
from app.core.config import settings
from app.core.exceptions import AuthenticationException, BaseApplicationException

router = APIRouter()
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

try:
    from app.api.routes import auth as auth_module

    AUTH_AVAILABLE = True
except ImportError:
    auth_module = None
    AUTH_AVAILABLE = False

IS_DEVELOPMENT = settings.environment == "development"
if IS_DEVELOPMENT:
    logger.warning("Running in development mode; authentication is disabled.")


async def get_optional_user(request: Request) -> dict[str, Any]:
    """Get user info as a dict to avoid serialization issues."""
    if IS_DEVELOPMENT:
        auth_header = request.headers.get("authorization", "")
        if not auth_header:
            return {
                "email": "dev@example.com",
                "roles": ["admin", "user"],
                "subscription_id": "12345678-1234-1234-1234-123456789012",
                "is_active": True,
            }

    if AUTH_AVAILABLE and auth_module is not None:
        token_data = await auth_module.auth_required(request)
        return {
            "email": token_data.email,
            "roles": token_data.roles,
            "subscription_id": token_data.subscription_id,
            "is_active": True,
        }

    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        raise AuthenticationException("Authentication required")

    return {"email": "token-user", "roles": ["user"], "subscription_id": None, "is_active": True}


def get_user_email(user: dict[str, Any] | Any) -> str:
    """Safely extract email from user object."""
    if isinstance(user, dict):
        return user.get("email", "anonymous")
    return getattr(user, "email", "anonymous")


@router.post("", response_model=None)
async def chat(
    req: ChatRequest,
    request: Request,
    current_user: Annotated[dict[str, Any], Depends(get_optional_user)],
    stream: bool = Query(True),
) -> Response:
    with tracer.start_as_current_span("api.chat") as span:
        user_email = get_user_email(current_user)
        span.set_attribute("auth.user", user_email)
        span.set_attribute("llm.provider.requested", req.provider or "")
        span.set_attribute("llm.model.requested", req.model or "")
        span.set_attribute("chat.stream", bool(stream))
        span.set_attribute("chat.tools.enabled", bool(req.enable_tools))

        try:
            if stream and not req.enable_tools:
                logger.info(
                    "chat stream start user=%s provider=%s model=%s",
                    user_email,
                    req.provider,
                    req.model,
                )
                return StreamingResponse(
                    _stream_plain_chat(req, current_user),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )

            logger.info(
                "chat request user=%s provider=%s model=%s",
                user_email,
                req.provider,
                req.model,
            )

            # Get correlation ID from middleware or create new one
            correlation_id = getattr(request.state, "correlation_id", None)

            text = await run_chat(
                req.input,
                [m.model_dump() for m in req.memory or []],
                req.provider,
                req.model,
                req.enable_tools,
                req.preferred_tool,
                req.allowlist,
                user_id=user_email,
                correlation_id=correlation_id,
            )

            logger.info(
                "chat completed user=%s bytes=%d",
                user_email,
                len(text or ""),
            )

            return JSONResponse(content=ChatResponse(output=text).model_dump())

        except BaseApplicationException as exc:
            msg = exc.user_message or "Failed to process request."
            span.set_status(Status(StatusCode.ERROR, msg))
            logger.exception("chat failed user=%s msg=%s", user_email, msg)
            return JSONResponse(content=ChatResponse(output=msg).model_dump())

        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.exception("chat failed user=%s", user_email)
            return JSONResponse(
                content=ChatResponse(output="Failed to process request.").model_dump()
            )


@router.post("/v2")
async def chat_v2(
    body: ChatRequestV2,
    current_user: Annotated[dict[str, Any], Depends(get_optional_user)],
) -> dict[str, Any]:
    with tracer.start_as_current_span("api.chat.v2") as span:
        user_email = get_user_email(current_user)
        span.set_attribute("auth.user", user_email)
        span.set_attribute("llm.provider.requested", body.provider or "")
        span.set_attribute("llm.model.requested", body.model or "")
        span.set_attribute("correlation_id", body.correlation_id)
        start = time.time()

        try:
            out = await run_chat(
                input_text=body.input,
                memory=body.memory,
                provider=body.provider,
                model=body.model,
                enable_tools=body.enable_tools,
            )

            took = time.time() - start
            span.set_attribute("chat.processing_time_ms", int(took * 1000))

            logger.info(
                "chat_v2 completed user=%s ms=%d bytes=%d",
                user_email,
                int(took * 1000),
                len(out or ""),
            )

            return {
                "response": out,
                "correlation_id": body.correlation_id,
                "processing_time": took,
                "user": user_email,
            }

        except BaseApplicationException as exc:
            msg = exc.user_message or "Failed to process request."
            span.set_status(Status(StatusCode.ERROR, msg))
            logger.exception("chat_v2 failed user=%s msg=%s", user_email, msg)
            return {
                "response": msg,
                "correlation_id": body.correlation_id,
                "processing_time": time.time() - start,
                "user": user_email,
            }

        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.exception("chat_v2 failed user=%s", user_email)
            return {
                "response": "Failed to process request.",
                "correlation_id": body.correlation_id,
                "processing_time": time.time() - start,
                "user": user_email,
            }


async def _stream_plain_chat(req: ChatRequest, user: dict[str, Any]) -> AsyncGenerator[bytes, None]:
    with tracer.start_as_current_span("api.chat.stream") as span:
        user_email = get_user_email(user)
        span.set_attribute("auth.user", user_email)
        span.set_attribute("llm.provider.requested", req.provider or "")
        span.set_attribute("llm.model.requested", req.model or "")

        try:
            llm, model = await get_provider_and_model(req.provider, req.model)
            memory = [m.model_dump() for m in req.memory or []]
            messages = [{"role": m["role"], "content": m["content"]} for m in memory]
            messages.append({"role": "user", "content": req.input})

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

            async for token in llm.chat_stream(model=model, messages=messages):
                if token:
                    yield f"data: {token}\n\n".encode()
                    await asyncio.sleep(0)
            yield b"data: [DONE]\n\n"

        except BaseApplicationException as exc:
            msg = exc.user_message or "Failed to process request."
            span.set_status(Status(StatusCode.ERROR, msg))
            logger.exception("chat stream failed user=%s msg=%s", user_email, msg)
            yield f"data: {msg}\n\n".encode()
            yield b"data: [DONE]\n\n"

        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.exception("chat stream failed user=%s", user_email)
            yield b"data: Failed to process request.\n\n"
            yield b"data: [DONE]\n\n"
