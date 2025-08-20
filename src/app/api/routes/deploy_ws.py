from __future__ import annotations
import asyncio
from typing import Annotated
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from pydantic import ValidationError
from uuid import uuid4
from app.api.routes.auth import require_role, TokenData
from app.services.deployment_manager import DeploymentManager
from app.events.schemas import DeploymentEvent
from app.events.provisioning_task import run_provisioning

router = APIRouter()
manager = DeploymentManager()
deploy_role_dependency = require_role("deploy")


@router.post("/start")
async def start_deploy(td: Annotated[TokenData, Depends(deploy_role_dependency)]) -> dict[str, str]:
    deployment_id = str(uuid4())
    asyncio.create_task(run_provisioning(deployment_id))
    return {"deployment_id": deployment_id}


@router.websocket("/ws/deploy/{deployment_id}")
async def deployment_stream(websocket: WebSocket, deployment_id: str, from_seq: int | None = Query(default=None)):
    await websocket.accept()
    try:
        async with manager.stream(deployment_id, from_seq=from_seq) as q:
            while True:
                event: DeploymentEvent = await q.get()
                await websocket.send_json(event.model_dump())
    except WebSocketDisconnect:
        return
    except ValidationError:
        await websocket.close(code=1003)
