from __future__ import annotations
from typing import Any
from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepType, StepResult
from app.ai.nlu import parse_provision_request
from app.tools.registry import ensure_tools_loaded, get_tool


class ProvisioningAgent(Agent[dict[str, Any], dict[str, Any]]):
    def __init__(
        self,
        user_id: str,
        context: AgentContext | None = None,
        config: dict[str, Any] | None = None
    ):
        super().__init__(context)
        self.user_id = user_id
        self.config = config or {}
        ensure_tools_loaded()

    async def plan(self, goal: str) -> ExecutionPlan:
        parsed = parse_provision_request(goal)

        steps = []

        if parsed.confidence < 0.3:
            steps.append(
                PlanStep(
                    type=StepType.MESSAGE,
                    name="clarification",
                    content="Request needs clarification"
                )
            )
            return ExecutionPlan(steps=steps)

        validation_step = PlanStep(
            type=StepType.TOOL,
            name="validate",
            tool="validation_tool",
            args={
                "resource_type": parsed.resource_type,
                "parameters": parsed.parameters
            }
        )
        steps.append(validation_step)

        if self.context.dry_run:
            preview_step = PlanStep(
                type=StepType.TOOL,
                name="preview",
                tool="provision_orchestrator",
                args={
                    "request": goal,
                    "plan_only": True,
                    "environment": self.context.environment
                },
                dependencies=["validate"]
            )
            steps.append(preview_step)
        else:
            provision_step = PlanStep(
                type=StepType.TOOL,
                name="provision",
                tool="provision_orchestrator",
                args=parsed.to_provision_args(),
                dependencies=["validate"],
                max_retries=2
            )
            steps.append(provision_step)

            verify_step = PlanStep(
                type=StepType.TOOL,
                name="verify",
                tool="verification_tool",
                args={"resource_type": parsed.resource_type},
                dependencies=["provision"]
            )
            steps.append(verify_step)

        return ExecutionPlan(
            steps=steps,
            metadata={
                "parsed_request": parsed.__dict__,
                "confidence": parsed.confidence
            }
        )

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        from app.runtime.streams import streaming_handler
        import time

        start_time = time.perf_counter()
        deployment_id = plan.metadata.get("deployment_id", "provision")

        async with streaming_handler.stream_deployment(deployment_id) as stream:
            results = {}
            step_results = []

            for step in plan.steps:
                await stream.send(f"Executing: {step.name}")

                try:
                    if step.type == StepType.TOOL and step.tool:
                        tool = get_tool(step.tool)
                        if tool:
                            result = await tool.run(**(step.args or {}))
                            results[step.name or step.tool] = result

                            step_results.append(
                                StepResult(
                                    step_name=step.name or step.tool,
                                    success=True,
                                    output=result
                                )
                            )
                            await stream.send(f"Completed: {step.name}")
                        else:
                            raise ValueError(f"Tool {step.tool} not found")

                    elif step.type == StepType.MESSAGE:
                        results[step.name or "message"] = step.content
                        step_results.append(
                            StepResult(
                                step_name=step.name or "message",
                                success=True,
                                output=step.content
                            )
                        )

                except Exception as e:
                    await stream.send(f"Failed: {step.name} - {str(e)}")
                    step_results.append(
                        StepResult(
                            step_name=step.name or "unknown",
                            success=False,
                            error=str(e)
                        )
                    )

                    if step.type != StepType.MESSAGE:
                        break

            duration = (time.perf_counter() - start_time) * 1000
            success = all(r.success for r in step_results)

            return ExecutionResult(
                success=success,
                result=results,
                duration_ms=duration,
                step_results=step_results,
                metadata={"deployment_id": deployment_id}
            )
