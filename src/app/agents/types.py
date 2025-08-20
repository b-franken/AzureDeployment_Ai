from __future__ import annotations
from typing import Protocol, Any
from pydantic import BaseModel


class Tool(Protocol):
    name: str
    async def run(self, **kwargs: Any) -> Any: ...


class LLM(Protocol):
    async def generate(self, messages: list[dict[str, str]]) -> str: ...


class PlanStep(BaseModel):
    tool: str
    args: dict[str, Any]


class ExecutionPlan(BaseModel):
    steps: list[PlanStep]
