from __future__ import annotations
from typing import Literal, Any
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from uuid import UUID, uuid4


class DeploymentEvent(BaseModel):
    version: int = 1
    type: Literal["progress", "log", "error", "complete"]
    payload: dict[str, Any]
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))
    seq: int = 0
    correlation_id: UUID = Field(default_factory=uuid4)
