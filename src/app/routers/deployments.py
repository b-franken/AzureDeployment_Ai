from __future__ import annotations
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from pydantic import ValidationError
from app.services.deployment_manager import DeploymentManager
from app.events.schemas import DeploymentEvent

router = APIRouter()
manager = DeploymentManager()


@router.websocket("/ws/deploy/{deployment_id}")
async def deployment_stream(websocket: WebSocket, deployment_id: str):
    await websocket.accept()
    try:
        async with manager.stream(deployment_id) as q:
            while True:
                event: DeploymentEvent = await q.get()
                await websocket.send_json(event.model_dump())
    except WebSocketDisconnect:
        return
    except ValidationError:
        await websocket.close(code=1003)
