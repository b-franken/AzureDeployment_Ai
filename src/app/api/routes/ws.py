# src/app/api/routes/ws.py
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from app.ai.llm.factory import get_provider_and_model
from app.core.logging import get_logger
from app.core.streams import streaming_handler
from app.core.schemas.domains.deployment import DeploymentEvent

router = APIRouter()
logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)

_ALLOWED = {o.strip() for o in os.getenv("WS_ALLOWED_ORIGINS", "*").split(",") if o.strip()}


def _origin_ok(origin: str) -> bool:
    if not _ALLOWED or "*" in _ALLOWED:
        return True
    return origin in _ALLOWED


async def _accept(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin", "")
    if not _origin_ok(origin):
        await ws.close(code=1008)
        return False
    await ws.accept(subprotocol="json")
    return True


class ChatInit(BaseModel):
    provider: str | None = None
    model: str | None = None
    memory: list[dict[str, str]] = Field(default_factory=list)
    input_: str = Field("", alias="input")


@router.websocket("/ws/chat")
async def chat_ws(ws: WebSocket) -> None:
    if not await _accept(ws):
        return
    with tracer.start_as_current_span("ws.chat") as span:
        span.set_attribute("ws.origin", ws.headers.get("origin", ""))
        try:
            while True:
                raw: dict[str, Any] = await ws.receive_json()
                msg_type = str(raw.get("type", "chat"))
                if msg_type == "ping":
                    await ws.send_json({"type": "pong"})
                    continue
                if msg_type != "chat":
                    await ws.send_json({"type": "error", "message": "unsupported_type"})
                    continue
                init = ChatInit.model_validate(raw.get("init") or raw)
                provider = (init.provider or "").strip()
                model = (init.model or "").strip()
                span.set_attribute("llm.provider", provider or "auto")
                span.set_attribute("llm.model", model or "auto")
                span.set_attribute("chat.memory.count", len(init.memory))
                span.set_attribute("chat.input.length", len(init.input_ or ""))
                logger.info("ws_chat_request", provider=provider or "auto", model=model or "auto")
                try:
                    llm, selected = await get_provider_and_model(provider or None, model or None)
                    messages = list(init.memory) + [{"role": "user", "content": init.input_}]
                    async for piece in llm.chat_stream(selected, messages):
                        await ws.send_json({"type": "delta", "data": piece})
                    await ws.send_json({"type": "done"})
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    logger.error(
                        "ws_chat_failed",
                        provider=provider or "auto",
                        model=model or "auto",
                        exc_info=True,
                    )
                    await ws.send_json({"type": "error", "message": "chat_failed"})
        except WebSocketDisconnect:
            logger.info("ws_chat_disconnected")
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error("ws_chat_unhandled_error", exc_info=True)
            try:
                await ws.send_json({"type": "error", "message": "internal_error"})
            finally:
                await ws.close(code=status.WS_1011_INTERNAL_ERROR)


@router.websocket("/ws/deploy/{deployment_id}")
async def deployment_stream(ws: WebSocket, deployment_id: str) -> None:
    if not await _accept(ws):
        return
    with tracer.start_as_current_span("ws.deploy") as span:
        span.set_attribute("deployment.id", deployment_id)
        logger.info("ws_deploy_stream_start", deployment_id=deployment_id)
        try:
            async for line in streaming_handler.stream_logs(deployment_id):
                evt = DeploymentEvent(
                    type="log", payload={"line": line}, timestamp=datetime.now(tz=UTC)
                )
                await ws.send_text(evt.model_dump_json())
            complete = DeploymentEvent(
                type="complete",
                payload={"deployment_id": deployment_id},
                timestamp=datetime.now(tz=UTC),
            )
            await ws.send_text(complete.model_dump_json())
            await ws.close(code=status.WS_1000_NORMAL_CLOSURE)
            logger.info("ws_deploy_stream_complete", deployment_id=deployment_id)
        except WebSocketDisconnect:
            logger.info("ws_deploy_stream_disconnected", deployment_id=deployment_id)
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error("ws_deploy_stream_failed", deployment_id=deployment_id, exc_info=True)
            try:
                await ws.send_json({"type": "error", "message": "stream_failed"})
            finally:
                await ws.close(code=status.WS_1011_INTERNAL_ERROR)


@router.websocket("/ws")
async def ws_alias(ws: WebSocket) -> None:
    await chat_ws(ws)


@router.websocket("/")
async def ws_root(ws: WebSocket) -> None:
    await ws.close(code=status.WS_1008_POLICY_VIOLATION)
