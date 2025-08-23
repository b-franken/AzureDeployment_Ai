from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.orchestrator import OrchestrationAgent
from app.ai.agents.provisioning import ProvisioningAgent
from app.ai.agents.reactive import Event, EventType, ReactiveAgent
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepResult, StepType
from app.ai.generator import generate_response
from app.ai.tools_router import maybe_call_tool


class CoordinatorAgent(Agent[dict[str, Any], dict[str, Any]]):
    def __init__(self, context: AgentContext | None = None):
        super().__init__(context)
        self.orchestrator = OrchestrationAgent(context)
        self.reactive = ReactiveAgent(context)
        self._handlers: dict[
            EventType, Callable[[Event], Awaitable[ExecutionResult[dict[str, Any]]]]
        ] = {}
        self._setup_event_handlers()

    async def plan(self, goal: str) -> ExecutionPlan:
        return await self._plan_coordination(goal)

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        results: list[StepResult] = []
        for step in plan.steps:
            res = await self._run_step(step)
            results.append(res)
            if not res.success:
                return ExecutionResult(success=False, result={"steps": results}, error=res.error)
        return ExecutionResult(success=True, result={"steps": results})

    async def handle_event(self, event: Event) -> ExecutionResult[dict[str, Any]]:
        handler = self._handlers.get(event.type)
        if handler:
            return await handler(event)
        return await self.reactive.handle(event)

    async def _plan_coordination(self, goal: str) -> ExecutionPlan:
        prompt = f"""
        Analyze this coordination request and identify sub-tasks: {goal}

        Constraints:
        - Output JSON with a steps array.
        - Each step has: type, name, description, optional tool, args, content.
        - Prefer TOOL steps for provisioning or integrations.
        """
        uid = self.context.user_id if self.context else "system"
        tid = self.context.thread_id if self.context else None
        agent_name = self.context.agent_name if self.context else self.__class__.__name__
        analysis = await generate_response(
            prompt.strip(),
            provider="openai",
            model="gpt-4o",
            user_id=uid,
            thread_id=tid,
            agent=agent_name or self.__class__.__name__,
            history_limit=20,
        )
        steps = self._extract_coordination_plan(analysis, goal)
        return ExecutionPlan(steps=steps)

    async def _run_step(self, step: PlanStep) -> StepResult:
        if step.type == StepType.TOOL:
            if step.tool == "provision_orchestrator":
                uid = self.context.user_id if self.context else "system"
                agent = ProvisioningAgent(uid, context=self.context)
                plan = await agent.plan(step.description or step.name or "provision")
                result = await agent.execute(plan)
                if result.success:
                    return StepResult(
                        step_name=step.name,
                        success=True,
                        output=getattr(result, "result", None),
                    )
                return StepResult(
                    step_name=step.name,
                    success=False,
                    error=getattr(result, "error", "provisioning failed"),
                )
            try:
                output = await maybe_call_tool(step.tool, step.args or {})
                return StepResult(step_name=step.name, success=True, output=output)
            except Exception as e:
                return StepResult(step_name=step.name, success=False, error=str(e))

        if step.type == StepType.MESSAGE:
            return StepResult(step_name=step.name, success=True, output=step.content or "")

        if step.type == StepType.SEQUENCE:
            seq_results: list[StepResult] = []
            for s in step.children or []:
                r = await self._run_step(s)
                seq_results.append(r)
                if not r.success:
                    return StepResult(
                        step_name=step.name, success=False, children=seq_results, error=r.error
                    )
            return StepResult(step_name=step.name, success=True, children=seq_results)

        if step.type == StepType.PARALLEL:
            tasks = [self._run_step(s) for s in step.children or []]
            done = await asyncio.gather(*tasks, return_exceptions=True)
            par_results: list[StepResult] = []
            ok = True
            for r in done:
                if isinstance(r, StepResult):
                    par_results.append(r)
                    ok = ok and r.success
                else:
                    par_results.append(StepResult(step_name=step.name, success=False, error=str(r)))
                    ok = False
            return StepResult(step_name=step.name, success=ok, children=par_results)

        if step.type == StepType.AGENT:
            plan = await self.orchestrator.plan(step.description or step.name)
            result = await self.orchestrator.execute(plan)
            if result.success:
                return StepResult(
                    step_name=step.name,
                    success=True,
                    output=getattr(result, "result", None),
                )
            return StepResult(
                step_name=step.name, success=False, error=getattr(result, "error", "agent failed")
            )

        return StepResult(step_name=step.name, success=False, error="unsupported step type")

    def _extract_coordination_plan(self, analysis: str, goal: str) -> list[PlanStep]:
        try:
            import json

            data = json.loads(analysis)
            raw_steps = data if isinstance(data, list) else data.get("steps", [])
            steps: list[PlanStep] = []
            for i, item in enumerate(raw_steps):
                if not isinstance(item, dict):
                    continue
                t = str(item.get("type", "message"))
                st = self._parse_step_type(t)
                steps.append(
                    PlanStep(
                        type=st,
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

        fallback: list[PlanStep] = []
        text = analysis.lower()
        if "provision" in text:
            fallback.append(
                PlanStep(
                    type=StepType.TOOL,
                    name="provision_task",
                    description="Provision requested resources",
                    tool="provision_orchestrator",
                    args={"goal": goal},
                )
            )
        if "monitor" in text:
            fallback.append(
                PlanStep(
                    type=StepType.MESSAGE,
                    name="setup_monitoring",
                    description="Configure monitoring",
                    content="Setting up monitoring",
                )
            )
        if not fallback:
            fallback.append(
                PlanStep(
                    type=StepType.MESSAGE,
                    name="analysis",
                    description="High level plan",
                    content=f"Analyze and coordinate for goal: {goal}",
                )
            )
        return fallback

    def _parse_step_type(self, raw: str) -> StepType:
        s = raw.strip()
        try:
            return StepType(s.lower())
        except Exception:
            try:
                return StepType[s.upper()]
            except Exception:
                return StepType.MESSAGE

    def _setup_event_handlers(self) -> None:
        self._handlers = {
            EventType.ALERT: self._handle_alert,
            EventType.DEPLOYMENT_FINISHED: self._handle_deployment_finished,
        }

    async def _handle_alert(self, event: Event) -> ExecutionResult[dict[str, Any]]:
        return await self.reactive.handle(event)

    async def _handle_deployment_finished(self, event: Event) -> ExecutionResult[dict[str, Any]]:
        return await self.reactive.handle(event)
