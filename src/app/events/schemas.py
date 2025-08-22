from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict

EventType = Literal["progress", "log", "error", "complete", "status"]


class DeploymentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))
    sequence: int = 0


__all__ = ["EventType", "DeploymentEvent"]
