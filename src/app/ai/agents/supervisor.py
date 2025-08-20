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
        self._task_queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._results: dict[str, Any] = {}

    def add_worker(self, agent: Agent, skills: set[str] | None = None, priority: int = 0) -> None:
        worker = WorkerAgent(agent=agent, skills=skills or set(), priority=priority)
        self.workers.append(worker)

    async def plan(self, goal: str) -> ExecutionPlan:
        from app.ai.generator import generate_response

        analysis = await generate_response(
            f"Break down this goal into subtasks and identify required skills: {goal}",
            memory=[],
            provider="openai",
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

    def _extract_tasks(self, analysis: str, goal: str) -> list[dict[str, Any]]:
        tasks = []

        if "provision" in goal.lower():
            tasks.append(
                {
                    "description": "Validate provisioning request",
                    "skills": {"validation"},
                    "priority": 1,
                }
            )
            tasks.append(
                {"description": "Execute provisioning", "skills": {"provisioning"}, "priority": 2}
            )

        if "monitor" in goal.lower():
            tasks.append(
                {"description": "Set up monitoring", "skills": {"monitoring"}, "priority": 3}
            )

        if not tasks:
            tasks.append({"description": goal, "skills": set(), "priority": 0})

        return tasks

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        import time

        start_time = time.perf_counter()

        tasks = []
        for step in plan.steps:
            task_data = step.args.get("task", {})
            tasks.append(self._assign_and_execute(step.name or "task", task_data))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        step_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                step_results.append(
                    StepResult(step_name=f"task_{i}", success=False, error=str(result))
                )
            else:
                step_results.append(StepResult(step_name=f"task_{i}", success=True, output=result))

        success = all(not isinstance(r, Exception) for r in results)

        return ExecutionResult(
            success=success,
            result={"tasks": results},
            duration_ms=(time.perf_counter() - start_time) * 1000,
            step_results=step_results,
        )

    async def _assign_and_execute(self, task_id: str, task_data: dict[str, Any]) -> Any:
        worker = self._select_worker(task_data)

        if not worker:
            raise ValueError(f"No available worker for task {task_id}")

        worker.current_load += 1

        try:
            result = await self._execute_with_worker(worker.agent, task_data)
            self._results[task_id] = result
            return result
        finally:
            worker.current_load -= 1

    def _select_worker(self, task_data: dict[str, Any]) -> WorkerAgent | None:
        required_skills = task_data.get("skills", set())

        eligible_workers = [
            w
            for w in self.workers
            if w.current_load < w.max_concurrent
            and (not required_skills or required_skills.intersection(w.skills))
        ]

        if not eligible_workers:
            return None

        if self.strategy == SupervisionStrategy.ROUND_ROBIN:
            return eligible_workers[0]

        elif self.strategy == SupervisionStrategy.LEAST_LOADED:
            return min(eligible_workers, key=lambda w: w.current_load)

        elif self.strategy == SupervisionStrategy.PRIORITY_BASED:
            return max(eligible_workers, key=lambda w: w.priority)

        elif self.strategy == SupervisionStrategy.SKILL_BASED:
            if required_skills:
                return max(
                    eligible_workers, key=lambda w: len(required_skills.intersection(w.skills))
                )
            return eligible_workers[0]

        return eligible_workers[0]

    async def _execute_with_worker(self, worker: Agent, task_data: dict[str, Any]) -> Any:
        goal = task_data.get("description", "Execute task")
        result = await worker.run(goal)
        return result.result if result.success else None
