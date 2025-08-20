from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from app.ai.agents.types import ExecutionPlan


class Agent(ABC):
    @abstractmethod
    async def plan(self, goal: str) -> ExecutionPlan: ...
    @abstractmethod
    async def run(self, plan: ExecutionPlan) -> dict[str, Any]: ...
