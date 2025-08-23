from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Anomaly(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    metric: str
    value: float
    severity: Literal["low", "medium", "high", "critical"]
    ts: datetime
    score: float = 0.0
    tags: dict[str, str] = {}


class Prediction(BaseModel):
    issue: str
    probability: float
    horizon_hours: int


class RootCause(BaseModel):
    cause: str
    confidence: float
    evidence: list[str]


class HealthReport(BaseModel):
    health_score: float
    anomalies: list[Anomaly]
    predictions: list[Prediction]
    root_causes: dict[str, RootCause]
    recommended_actions: list[str]
