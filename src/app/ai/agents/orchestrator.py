from __future__ import annotations

import asyncio
from typing import Any

from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepResult, StepType
from app.ai.generator import generate_response
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
        logger.debug("planning execution for goal %s", goal)
        prompt = f"""
        Create an execution plan for: {goal}

        Context:
        - Environment: {self.context.environment}
        - Dry run: {self.context.dry_run}

        Identify the necessary steps and their dependencies.
        """
        analysis = await generate_response(
            prompt.strip(),
            provider="openai",
            model="gpt-4o",
            user_id=self.context.user_id,
            thread_id=self.context.thread_id,
            agent=self.context.agent_name or self.__class__.__name__,
            history_limit=40,
        )
        steps = self._parse_plan_response(analysis, goal)
        return ExecutionPlan(steps=steps, metadata={"goal": goal, "context": self.context.metadata})

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        logger.debug("executing plan with %d steps", len(plan.steps))
        results: list[StepResult] = []
        for step in plan.steps:
            res = await self._run_step(step)
            results.append(res)
            if not res.success:
                return ExecutionResult(success=False, result={"steps": results})
        return ExecutionResult(success=True, result={"steps": results})

    async def _run_step(self, step: PlanStep) -> StepResult:
        logger.debug("running step %s of type %s", step.name, step.type)
        if step.type == StepType.TOOL:
            try:
                output = await maybe_call_tool(step.tool, step.args or {})
                return StepResult(step_name=step.name, success=True, output=output)
            except Exception as e:
                return StepResult(step_name=step.name, success=False, error=str(e))
        if step.type == StepType.MESSAGE:
            return StepResult(step_name=step.name, success=True, output=step.content or "")
        if step.type == StepType.SEQUENCE:
            sequence_results: list[StepResult] = []
            for s in step.children or []:
                r = await self._run_step(s)
                sequence_results.append(r)
                if not r.success:
                    return StepResult(step_name=step.name, success=False, children=sequence_results)
            return StepResult(step_name=step.name, success=True, children=sequence_results)
        if step.type == StepType.PARALLEL:
            tasks = [self._run_step(s) for s in step.children or []]
            done = await asyncio.gather(*tasks, return_exceptions=True)
            child_results: list[StepResult] = []
            ok = True
            for r in done:
                if isinstance(r, StepResult):
                    child_results.append(r)
                    ok = ok and r.success
                else:
                    child_results.append(
                        StepResult(step_name=step.name, success=False, error=str(r))
                    )
                    ok = False
            return StepResult(step_name=step.name, success=ok, children=child_results)
        if step.type == StepType.AGENT:
            agent = self.agents.get(step.agent or "")
            if not agent:
                return StepResult(step_name=step.name, success=False, error="agent not found")
            plan = await agent.plan(step.description or step.name)
            result = await agent.execute(plan)
            if result.success:
                return StepResult(
                    step_name=step.name,
                    success=True,
                    output=result.result if hasattr(result, "result") else None,
                )
            return StepResult(
                step_name=step.name, success=False, error=getattr(result, "error", "agent failed")
            )
        return StepResult(step_name=step.name, success=False, error="unsupported step type")

    def _parse_plan_response(self, text: str, goal: str) -> list[PlanStep]:
        try:
            import json

            data = json.loads(text)
            steps: list[PlanStep] = []
            for i, item in enumerate(data if isinstance(data, list) else data.get("steps", [])):
                steps.append(
                    PlanStep(
                        type=StepType(item.get("type", "message").lower()),
                        name=item.get("name", f"step_{i}"),
                        description=item.get("description"),
                        tool=item.get("tool"),
                        args=item.get("args"),
                        content=item.get("content"),
                        children=None,
                    )
                )
            if steps:
                return steps
        except Exception:
            pass
        return [
            PlanStep(
                type=StepType.MESSAGE,
                name="default",
                description="auto-generated plan",
                content=f"Plan for goal: {goal}",
            )
        ]
