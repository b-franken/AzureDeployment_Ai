from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepType
from app.memory.storage import get_async_store


@dataclass
class Experience:
    goal: str
    plan: ExecutionPlan
    result: ExecutionResult
    feedback: float
    metadata: dict[str, Any] = field(default_factory=dict)


class LearningAgent(Agent[list[Experience], dict[str, Any]]):
    def __init__(self, context: AgentContext | None = None):
        super().__init__(context)
        self.experiences: list[Experience] = []
        self.strategies: dict[str, float] = {}
        self.exploration_rate = 0.1

    async def _explore_new_strategy(self, goal: str) -> ExecutionPlan:
        from app.ai.generator import generate_response

        strategy_prompt = f"""
        Generate a new strategy for: {goal}
        
        Consider different approaches and be creative.
        """

        response = await generate_response(strategy_prompt, provider="openai", user_id=self.context.user_id)

        steps = self._parse_strategy_response(response, goal)

        return ExecutionPlan(steps=steps, metadata={"strategy": "exploration", "goal": goal})
