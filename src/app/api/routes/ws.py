from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from app.ai.llm.factory import get_provider_and_model
from app.core.streams import streaming_handler
from app.events.schemas import DeploymentEvent

router = APIRouter()


class ChatInit(BaseModel):
    provider: str | None = None
    model: str | None = None
    memory: list[dict[str, str]] = Field(default_factory=list)
    input_: str = Field("", alias="input")


@router.websocket("/ws/chat")
async def chat_ws(ws: WebSocket) -> None:
    await ws.accept(subprotocol="json")
    try:
        raw = await ws.receive_json()
        init = ChatInit.model_validate(raw)
        provider = (init.provider or "").strip()
        model = (init.model or "").strip()
        llm, selected = await get_provider_and_model(provider or None, model or None)
        messages = list(init.memory) + [{"role": "user", "content": init.input_}]
        async for piece in llm.chat_stream(selected, messages):
            await ws.send_json({"type": "delta", "data": piece})
        await ws.send_json({"type": "done"})
        await ws.close(code=status.WS_1000_NORMAL_CLOSURE)
    except WebSocketDisconnect:
        return
    except Exception as e:
        await ws.send_json({"type": "error", "message": str(e)})
        await ws.close(code=status.WS_1011_INTERNAL_ERROR)


@router.websocket("/ws/deploy/{deployment_id}")
async def deployment_stream(ws: WebSocket, deployment_id: str) -> None:
    await ws.accept(subprotocol="json")
    try:
        async for line in streaming_handler.stream_logs(deployment_id):
            evt = DeploymentEvent(
                type="log",
                payload={"line": line},
                timestamp=datetime.now(tz=UTC),
            )
            await ws.send_text(evt.model_dump_json())
        complete = DeploymentEvent(
            type="complete",
            payload={"deployment_id": deployment_id},
            timestamp=datetime.now(tz=UTC),
        )
        await ws.send_text(complete.model_dump_json())
        await ws.close(code=status.WS_1000_NORMAL_CLOSURE)
    except WebSocketDisconnect:
        return
