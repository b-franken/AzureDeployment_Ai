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
    def __init__(self, context: AgentContext | None = None) -> None:
        super().__init__(context)
        self.agents: dict[str, Agent[Any, Any]] = {}
        self._execution_cache: dict[str, Any] = {}

    def register_agent(self, name: str, agent: Agent[Any, Any]) -> None:
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
        async with self.tracer.trace_operation(
            "orchestrate_execution",
            {"steps_count": len(plan.steps), "registered_agents": len(self.agents)},
        ):
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
                # Convert tool call to text format for maybe_call_tool
                import json

                tool_input = f"Use {step.tool or 'unknown_tool'}"
                if step.args:
                    tool_input += f" with args: {json.dumps(step.args)}"
                output = await maybe_call_tool(tool_input, enable_tools=True)
                return StepResult(step_name=step.name or "tool_step", success=True, output=output)
            except Exception as e:
                return StepResult(step_name=step.name or "tool_step", success=False, error=str(e))
        if step.type == StepType.MESSAGE:
            return StepResult(
                step_name=step.name or "message_step", success=True, output=step.content or ""
            )
        if step.type == StepType.SEQUENCE:
            sequence_results: list[StepResult] = []
            for s in step.children or []:
                r = await self._run_step(s)
                sequence_results.append(r)
                if not r.success:
                    return StepResult(
                        step_name=step.name or "sequence_step",
                        success=False,
                        children=sequence_results,
                    )
            return StepResult(
                step_name=step.name or "sequence_step", success=True, children=sequence_results
            )
        if step.type == StepType.PARALLEL:
            child_steps = step.children or []
            if not child_steps:
                logger.warning("parallel step '%s' has no children", step.name)
                return StepResult(
                    step_name=step.name or "parallel_step",
                    success=False,
                    error="no child steps provided",
                )

            logger.debug("executing %d parallel tasks for step '%s'", len(child_steps), step.name)
            tasks = [self._run_step(s) for s in child_steps]

            try:
                done = await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                logger.error("parallel execution failed for step '%s': %s", step.name, e)
                return StepResult(
                    step_name=step.name or "parallel_step",
                    success=False,
                    error=f"parallel execution failed: {e}",
                )

            child_results: list[StepResult] = []
            success_count = 0

            for i, result in enumerate(done):
                if isinstance(result, StepResult):
                    child_results.append(result)
                    if result.success:
                        success_count += 1
                    else:
                        logger.debug("parallel task %d failed: %s", i, result.error)
                else:
                    error_msg = str(result)
                    logger.error("parallel task %d raised exception: %s", i, error_msg)
                    child_results.append(
                        StepResult(step_name=step.name or "unknown", success=False, error=error_msg)
                    )

            overall_success = success_count == len(child_results)
            logger.debug(
                "parallel step '%s' completed: %d/%d tasks successful",
                step.name,
                success_count,
                len(child_results),
            )

            return StepResult(
                step_name=step.name or "parallel_step",
                success=overall_success,
                children=child_results,
            )
        if step.type == StepType.AGENT:
            agent_name = step.agent or ""
            if not agent_name:
                logger.error("agent step '%s' missing agent name", step.name)
                return StepResult(
                    step_name=step.name or "agent_step",
                    success=False,
                    error="agent name not specified",
                )

            agent = self.agents.get(agent_name)
            if not agent:
                logger.error("agent '%s' not found for step '%s'", agent_name, step.name)
                available_agents = list(self.agents.keys())
                return StepResult(
                    step_name=step.name or "agent_step",
                    success=False,
                    error=f"agent '{agent_name}' not found. Available agents: {available_agents}",
                )

            goal = step.description or step.name or "execute"
            logger.debug("executing agent '%s' with goal '%s'", agent_name, goal)

            try:
                plan = await agent.plan(goal)
                logger.debug("agent '%s' created plan with %d steps", agent_name, len(plan.steps))
            except Exception as e:
                logger.error("agent '%s' planning failed: %s", agent_name, e)
                return StepResult(
                    step_name=step.name or "agent_step",
                    success=False,
                    error=f"agent planning failed: {e}",
                )

            try:
                execution_result = await agent.execute(plan)
                logger.debug(
                    "agent '%s' execution completed, success=%s",
                    agent_name,
                    execution_result.success,
                )
            except Exception as e:
                logger.error("agent '%s' execution failed: %s", agent_name, e)
                return StepResult(
                    step_name=step.name or "agent_step",
                    success=False,
                    error=f"agent execution failed: {e}",
                )

            if execution_result.success:
                return StepResult(
                    step_name=step.name or "agent_step",
                    success=True,
                    output=execution_result.result if hasattr(execution_result, "result") else None,
                )

            error_msg = getattr(execution_result, "error", "agent failed")
            logger.debug("agent '%s' execution failed: %s", agent_name, error_msg)
            return StepResult(
                step_name=step.name or "agent_step",
                success=False,
                error=error_msg,
            )
        return StepResult(
            step_name=step.name or "unknown_step", success=False, error="unsupported step type"
        )

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
        except Exception as e:
            logger.warning(
                "Failed to parse orchestration analysis",
                error=str(e),
                text_length=len(text) if text else 0,
            )
        return [
            PlanStep(
                type=StepType.MESSAGE,
                name="default",
                description="auto-generated plan",
                content=f"Plan for goal: {goal}",
            )
        ]
