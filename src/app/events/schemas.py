from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal["progress", "log", "error", "complete", "status"]


class DeploymentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sequence: int = 0


__all__ = ["DeploymentEvent", "EventType"]
