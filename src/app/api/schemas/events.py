from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

EventType = Literal["progress", "log", "error", "complete", "status"]


class DeploymentEvent(BaseModel):
    type: EventType
    payload: dict[str, Any] = {}
    timestamp: datetime
