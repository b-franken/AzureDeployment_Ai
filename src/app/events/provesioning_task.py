from __future__ import annotations
import asyncio
from app.services.deployment_manager import DeploymentManager
from app.events.schemas import DeploymentEvent

manager = DeploymentManager()


async def run_provisioning(deployment_id: str) -> None:
    manager.publish(deployment_id, DeploymentEvent(
        type="progress", payload={"stage": "start"}))
    await asyncio.sleep(1)
    manager.publish(deployment_id, DeploymentEvent(
        type="log", payload={"message": "creating infrastructure"}))
    await asyncio.sleep(1)
    manager.publish(deployment_id, DeploymentEvent(
        type="complete", payload={"status": "ok"}))
