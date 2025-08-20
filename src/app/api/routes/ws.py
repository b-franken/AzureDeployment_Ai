from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.events.schemas import DeploymentEvent
from app.runtime.streams import streaming_handler

router = APIRouter()


@router.websocket("/ws/deploy/{deployment_id}")
async def deployment_stream(websocket: WebSocket, deployment_id: str) -> None:
    await websocket.accept(subprotocol="json")
    try:
        async for line in streaming_handler.stream_logs(deployment_id):
            evt = DeploymentEvent(
                type="log",
                payload={"line": line},
                timestamp=datetime.now(tz=UTC),
            )
            await websocket.send_text(evt.model_dump_json())
        complete = DeploymentEvent(
            type="complete",
            payload={"deployment_id": deployment_id},
            timestamp=datetime.now(tz=UTC),
        )
        await websocket.send_text(complete.model_dump_json())
        await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
    except WebSocketDisconnect:
        return
