from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepResult, StepType
from app.core.logging import get_logger

logger = get_logger(__name__)


class SupervisionStrategy(Enum):
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    PRIORITY_BASED = "priority_based"
    SKILL_BASED = "skill_based"


@dataclass
class WorkerAgent:
    agent: Agent
    skills: set[str] = field(default_factory=set)
    current_load: int = 0
    max_concurrent: int = 3
    priority: int = 0


class SupervisorAgent(Agent[dict[str, Any], dict[str, Any]]):
    def __init__(
        self,
        context: AgentContext | None = None,
        strategy: SupervisionStrategy = SupervisionStrategy.LEAST_LOADED,
    ):
        super().__init__(context)
        self.strategy = strategy
        self.workers: list[WorkerAgent] = []
        self._task_queue: asyncio.Queue[tuple[str,
                                              dict[str, Any]]] = asyncio.Queue()
        self._results: dict[str, Any] = {}

    def add_worker(self, agent: Agent, skills: set[str] | None = None, priority: int = 0) -> None:
        worker = WorkerAgent(
            agent=agent, skills=skills or set(), priority=priority)
        self.workers.append(worker)

    async def plan(self, goal: str) -> ExecutionPlan:
        from app.ai.generator import generate_response

        analysis = await generate_response(
            f"Break down this goal into subtasks and identify required skills: {goal}",
            provider="openai",
            user_id=self.context.user_id,
        )

        tasks = self._extract_tasks(analysis, goal)

        steps = []
        for task_id, task in enumerate(tasks):
            step = PlanStep(
                type=StepType.PARALLEL,
                name=f"task_{task_id}",
                description=task["description"],
                args={"task": task},
            )
            steps.append(step)

        return ExecutionPlan(steps=steps, metadata={"total_tasks": len(tasks)})
