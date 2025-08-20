from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel


class PlanStep(BaseModel):
    kind: Literal["tool", "message"]
    name: str | None = None
    args: dict[str, Any] | None = None
    content: str | None = None


class ExecutionPlan(BaseModel):
    steps: list[PlanStep]
