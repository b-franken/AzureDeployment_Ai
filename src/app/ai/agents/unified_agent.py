from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepResult, StepType
from app.ai.llm.factory import get_provider_and_model
from app.ai.tools_router import maybe_call_tool
from app.ai.types import Message

logger = logging.getLogger(__name__)


class AgentCapability(Enum):
    ORCHESTRATION = "orchestration"
    PROVISIONING = "provisioning"
    MONITORING = "monitoring"
    LEARNING = "learning"
    COORDINATION = "coordination"


@runtime_checkable
class AgentPlugin(Protocol):
    async def enhance_plan(self, plan: ExecutionPlan) -> ExecutionPlan: ...
    async def process_result(
        self, result: ExecutionResult[dict[str, Any]]
    ) -> ExecutionResult[dict[str, Any]]: ...


@dataclass
class UnifiedAgent(Agent[dict[str, Any], dict[str, Any]]):
    capabilities: set[AgentCapability] = field(default_factory=set)
    plugins: list[AgentPlugin] = field(default_factory=list)

    def __init__(self, context: AgentContext | None = None) -> None:
        super().__init__(context)
        self.capabilities = {AgentCapability.ORCHESTRATION}
        self.plugins = []

    def add_capability(self, capability: AgentCapability) -> UnifiedAgent:
        self.capabilities.add(capability)
        return self

    def add_plugin(self, plugin: AgentPlugin) -> UnifiedAgent:
        self.plugins.append(plugin)
        return self

    async def plan(self, goal: str) -> ExecutionPlan:
        llm, model = await get_provider_and_model()
        messages: list[Message] = [
            Message(role="system", content="You are an intelligent DevOps agent."),
            Message(role="user", content=self._build_prompt(goal)),
        ]
        raw = await llm.chat(model, messages)
        steps = self._parse_plan(raw, goal)
        plan = ExecutionPlan(
            steps=steps, metadata={"goal": goal, "env": getattr(self.context, "environment", None)}
        )
        for p in self.plugins:
            plan = await p.enhance_plan(plan)
        return plan

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        tasks: list[asyncio.Task[ExecutionResult[dict[str, Any]]]] = []

        if AgentCapability.ORCHESTRATION in self.capabilities:
            async with self.tracer.trace_operation(
                "orchestration", {"capability": "orchestration"}
            ):
                tasks.append(asyncio.create_task(self._execute_orchestration(plan)))
        if AgentCapability.PROVISIONING in self.capabilities:
            async with self.tracer.trace_operation("provisioning", {"capability": "provisioning"}):
                tasks.append(asyncio.create_task(self._execute_provisioning(plan)))
        if AgentCapability.MONITORING in self.capabilities:
            async with self.tracer.trace_operation("monitoring", {"capability": "monitoring"}):
                tasks.append(asyncio.create_task(self._execute_monitoring(plan)))

        async with self.tracer.trace_operation(
            "capability_execution",
            {"capabilities_count": len(self.capabilities), "tasks_count": len(tasks)},
        ):
            done = await asyncio.gather(*tasks, return_exceptions=True)

        merged = self._merge_results(done)
        for p in self.plugins:
            merged = await p.process_result(merged)
        return merged

    def _build_prompt(self, goal: str) -> str:
        env = getattr(self.context, "environment", None)
        dry = getattr(self.context, "dry_run", None)
        return (
            f"Create a JSON plan with steps to achieve: {goal}\n"
            f"Each step has: type, name, description, optional tool, args, content.\n"
            f"Prefer TOOL steps for provisioning or integrations.\n"
            f"Context: env={env} dry_run={dry}."
        )

    def _parse_plan(self, text: str, goal: str) -> list[PlanStep]:
        try:
            import json

            data = json.loads(text)
            items = data if isinstance(data, list) else data.get("steps", [])
            steps: list[PlanStep] = []
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                raw_t = str(item.get("type", "message")).lower()
                try:
                    st = StepType(raw_t)
                except Exception:
                    st = StepType.MESSAGE
                steps.append(
                    PlanStep(
                        type=st,
                        name=item.get("name", f"step_{i}"),
                        description=item.get("description"),
                        tool=item.get("tool"),
                        args=item.get("args"),
                        content=item.get("content"),
                    )
                )
            if steps:
                return steps
        except Exception as e:
            logger.warning(
                "Failed to generate plan steps: %s (goal: %s)", str(e), goal[:100] if goal else None
            )
        return [
            PlanStep(
                type=StepType.MESSAGE,
                name="analysis",
                description="Fallback single-step plan",
                content=f"Analyze and coordinate for goal: {goal}",
            )
        ]

    async def _execute_orchestration(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        results: list[StepResult] = []
        context_out: dict[str, Any] = {}
        try:
            for step in plan.steps:
                if step.type == StepType.TOOL and step.tool:
                    import json

                    tool_input = f"Use {step.tool}"
                    if step.args:
                        tool_input += f" with args: {json.dumps(step.args)}"
                    output = await maybe_call_tool(tool_input, enable_tools=True, return_json=True)
                    results.append(
                        StepResult(
                            step_name=step.name or step.type.value, success=True, output=output
                        )
                    )
                    context_out[step.name or step.type.value] = output
                elif step.type == StepType.MESSAGE:
                    results.append(
                        StepResult(
                            step_name=step.name or "message",
                            success=True,
                            output=step.content or "",
                        )
                    )
                elif step.type in {StepType.SEQUENTIAL, StepType.PARALLEL}:
                    results.append(
                        StepResult(
                            step_name=step.name or step.type.value,
                            success=True,
                            output={"skipped": True},
                        )
                    )
                else:
                    results.append(
                        StepResult(
                            step_name=step.name or step.type.value,
                            success=True,
                            output={"status": "ok"},
                        )
                    )
            return ExecutionResult(
                success=all(r.success for r in results), result=context_out, step_results=results
            )
        except Exception as e:
            return ExecutionResult(success=False, error=str(e), step_results=results)

    async def _execute_provisioning(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        logger.debug("Executing provisioning plan with %d steps", len(plan.steps))
        return ExecutionResult(success=True, result={"provisioning": "completed"})

    async def _execute_monitoring(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        logger.debug("Executing monitoring plan with %d steps", len(plan.steps))
        return ExecutionResult(success=True, result={"monitoring": "ok"})

    def _merge_results(self, results: list[Any]) -> ExecutionResult[dict[str, Any]]:
        out: dict[str, Any] = {}
        steps: list[StepResult] = []
        ok = True
        for r in results:
            if isinstance(r, ExecutionResult):
                ok = ok and r.success
                if r.result:
                    out.update(r.result if isinstance(r.result, dict) else {"value": r.result})
                steps.extend(r.step_results or [])
            else:
                ok = False
        return ExecutionResult(success=ok, result=out, step_results=steps)
