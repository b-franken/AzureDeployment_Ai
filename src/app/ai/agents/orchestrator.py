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
            planning_prompt, memory=[], provider="openai", model="gpt-4o"
        )

        steps = self._parse_plan_response(response, goal)

        return ExecutionPlan(steps=steps, metadata={"goal": goal, "context": self.context.metadata})

    def _parse_plan_response(self, response: str, goal: str) -> list[PlanStep]:
        steps = []

        if "provision" in goal.lower() or "create" in goal.lower():
            steps.append(
                PlanStep(
                    type=StepType.TOOL,
                    name="validate_requirements",
                    tool="validation_tool",
                    args={"goal": goal},
                )
            )

            steps.append(
                PlanStep(
                    type=StepType.TOOL,
                    name="provision_resources",
                    tool="provision_orchestrator",
                    args={"request": goal},
                    dependencies=["validate_requirements"],
                )
            )

            if not self.context.dry_run:
                steps.append(
                    PlanStep(
                        type=StepType.TOOL,
                        name="verify_deployment",
                        tool="verification_tool",
                        dependencies=["provision_resources"],
                    )
                )

        return steps

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        import time

        start_time = time.perf_counter()

        step_results = []
        execution_state = {}

        try:
            for step in self._order_steps_by_dependencies(plan.steps):
                if not self._check_dependencies(step, step_results):
                    step_results.append(
                        StepResult(
                            step_name=step.name or "unnamed",
                            success=False,
                            error="Dependencies not satisfied",
                        )
                    )
                    continue

                result = await self._execute_step(step, execution_state)
                step_results.append(result)

                if not result.success and step.type != StepType.MESSAGE:
                    break

            success = all(r.success for r in step_results if r.step_name != "message")

            return ExecutionResult(
                success=success,
                result=execution_state,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                step_results=step_results,
            )

        except Exception as e:
            logger.error(f"Execution failed: {e}")
            return ExecutionResult(
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - start_time) * 1000,
                step_results=step_results,
            )

    async def _execute_step(self, step: PlanStep, state: dict[str, Any]) -> StepResult:
        import time

        start_time = time.perf_counter()

        try:
            if step.type == StepType.TOOL and step.tool:
                output = await self._execute_tool(step, state)
            elif step.type == StepType.MESSAGE:
                output = step.content
            elif step.type == StepType.PARALLEL:
                output = await self._execute_parallel(step, state)
            elif step.type == StepType.CONDITIONAL:
                output = await self._execute_conditional(step, state)
            else:
                output = None

            duration = (time.perf_counter() - start_time) * 1000

            if step.name:
                state[step.name] = output

            return StepResult(
                step_name=step.name or step.type.value,
                success=True,
                output=output,
                duration_ms=duration,
            )

        except Exception as e:
            if step.retry_count < step.max_retries:
                step.retry_count += 1
                await asyncio.sleep(2**step.retry_count)
                return await self._execute_step(step, state)

            return StepResult(
                step_name=step.name or step.type.value,
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - start_time) * 1000,
                retries_used=step.retry_count,
            )

    async def _execute_tool(self, step: PlanStep, state: dict[str, Any]) -> Any:
        if not step.tool:
            raise ValueError("Tool not specified")

        args = self._resolve_args(step.args or {}, state)

        cache_key = f"{step.tool}:{str(args)}"
        if self.context.enable_caching and cache_key in self._execution_cache:
            return self._execution_cache[cache_key]

        result = await maybe_call_tool(
            user_input=args.get("request", ""),
            memory=[],
            enable_tools=True,
            preferred_tool=step.tool,
            context=self.context,
            return_json=True,
        )

        if self.context.enable_caching:
            self._execution_cache[cache_key] = result

        return result

    async def _execute_parallel(self, step: PlanStep, state: dict[str, Any]) -> list[Any]:
        tasks = []
        for sub_step in step.args.get("steps", []):
            tasks.append(self._execute_step(sub_step, state))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if not isinstance(r, Exception)]

    async def _execute_conditional(self, step: PlanStep, state: dict[str, Any]) -> Any:
        condition = step.conditions or {}
        if self._evaluate_condition(condition, state):
            return await self._execute_step(step.args["then_step"], state)
        elif "else_step" in step.args:
            return await self._execute_step(step.args["else_step"], state)
        return None

    def _order_steps_by_dependencies(self, steps: list[PlanStep]) -> list[PlanStep]:
        ordered = []
        completed = set()

        while len(ordered) < len(steps):
            for step in steps:
                if step in ordered:
                    continue

                deps_satisfied = all(dep in completed for dep in step.dependencies)

                if deps_satisfied:
                    ordered.append(step)
                    if step.name:
                        completed.add(step.name)

        return ordered

    def _check_dependencies(self, step: PlanStep, results: list[StepResult]) -> bool:
        completed_steps = {r.step_name for r in results if r.success}

        return all(dep in completed_steps for dep in step.dependencies)

    def _resolve_args(self, args: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str) and value.startswith("$"):
                var_name = value[1:]
                resolved[key] = state.get(var_name, value)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_args(value, state)
            else:
                resolved[key] = value
        return resolved

    def _evaluate_condition(self, condition: dict[str, Any], state: dict[str, Any]) -> bool:
        if "equals" in condition:
            return state.get(condition["field"]) == condition["equals"]
        if "not_equals" in condition:
            return state.get(condition["field"]) != condition["not_equals"]
        if "exists" in condition:
            return condition["exists"] in state
        if "not_exists" in condition:
            return condition["not_exists"] not in state
        return True
