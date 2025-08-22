from __future__ import annotations

import asyncio
from typing import Any

from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepResult, StepType
from app.ai.tools_router import maybe_call_tool
from app.core.logging import get_logger

logger = get_logger(__name__)


class OrchestrationAgent(Agent[dict[str, Any], dict[str, Any]]):
    def __init__(self, context: AgentContext | None = None):
        super().__init__(context)
        self.agents: dict[str, Agent] = {}
        self._execution_cache: dict[str, Any] = {}

    def register_agent(self, name: str, agent: Agent) -> None:
        self.agents[name] = agent

    async def plan(self, goal: str) -> ExecutionPlan:
        from app.ai.generator import generate_response

        planning_prompt = f"""
        Create an execution plan for: {goal}
        
        Context:
        - Environment: {self.context.environment}
        - Dry run: {self.context.dry_run}
        
        Identify the necessary steps and their dependencies.
        """

        response = await generate_response(
            planning_prompt, provider="openai", model="gpt-4o", user_id=self.context.user_id
        )

        steps = self._parse_plan_response(response, goal)

        return ExecutionPlan(steps=steps, metadata={"goal": goal, "context": self.context.metadata})
