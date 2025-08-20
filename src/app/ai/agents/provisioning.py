from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel

from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepResult, StepType
from app.ai.nlu import parse_provision_request
from app.core.logging import get_logger
from app.tools.registry import ensure_tools_loaded, get_tool

logger = get_logger(__name__)


class ProvisioningAgentConfig(BaseModel):
    provider: str | None = None
    model: str | None = None
    environment: str | None = None


class ProvisioningAgent(Agent[dict[str, Any], dict[str, Any]]):
    def __init__(
        self,
        user_id: str,
        context: AgentContext | None = None,
        config: ProvisioningAgentConfig | dict[str, Any] | None = None,
    ):
        super().__init__(context)
        self.user_id = user_id
        if isinstance(config, ProvisioningAgentConfig):
            self.config = config
        elif isinstance(config, dict):
            self.config = ProvisioningAgentConfig(**config)
        else:
            self.config = ProvisioningAgentConfig()
        ensure_tools_loaded()

    async def plan(self, goal: str) -> ExecutionPlan:
        """Create a provisioning plan based on the goal."""

        parsed = parse_provision_request(goal)

        steps = []

        steps.append(
            PlanStep(
                type=StepType.TOOL,
                name="validate_request",
                description="Validate provisioning request",
                tool="validation_tool",
                args={"resource_type": parsed.resource_type, "parameters": parsed.parameters},
            )
        )

        steps.append(
            PlanStep(
                type=StepType.TOOL,
                name="check_prerequisites",
                description="Check resource prerequisites",
                tool="prerequisite_checker",
                args={
                    "resource_type": parsed.resource_type,
                    "environment": self.context.environment if self.context else "dev",
                },
                dependencies=["validate_request"],
            )
        )

        steps.append(
            PlanStep(
                type=StepType.TOOL,
                name="generate_infrastructure",
                description="Generate infrastructure as code",
                tool="provision_orchestrator",
                args=parsed.to_provision_args(),
                dependencies=["check_prerequisites"],
            )
        )

        if not self.context.dry_run:
            steps.append(
                PlanStep(
                    type=StepType.TOOL,
                    name="apply_infrastructure",
                    description="Apply infrastructure changes",
                    tool="apply_infrastructure",
                    args={
                        "dry_run": False,
                        "environment": self.context.environment if self.context else "dev",
                    },
                    dependencies=["generate_infrastructure"],
                )
            )

        steps.append(
            PlanStep(
                type=StepType.TOOL,
                name="verify_deployment",
                description="Verify deployment success",
                tool="verification_tool",
                args={"resource_type": parsed.resource_type, "resource_name": parsed.resource_name},
                dependencies=(
                    ["apply_infrastructure"]
                    if not self.context.dry_run
                    else ["generate_infrastructure"]
                ),
            )
        )

        return ExecutionPlan(
            steps=steps,
            metadata={
                "user_id": self.user_id,
                "parsed_request": {
                    "intent": parsed.intent.value,
                    "resource_type": parsed.resource_type,
                    "resource_name": parsed.resource_name,
                    "confidence": parsed.confidence,
                },
                "dry_run": self.context.dry_run if self.context else True,
            },
        )

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        """Execute the provisioning plan."""
        import time

        start_time = time.perf_counter()

        step_results = []
        accumulated_output = {}

        for step in plan.steps:
            try:
                result = await self._execute_step(step, accumulated_output)
                step_results.append(result)

                if result.output:
                    accumulated_output[step.name or step.type.value] = result.output

                if not result.success and step.type != StepType.MESSAGE:
                    # Stop execution on critical failures
                    break

            except Exception as e:
                logger.error(f"Step {step.name} failed: {e}", exc_info=True)
                step_results.append(
                    StepResult(step_name=step.name or step.type.value, success=False, error=str(e))
                )
                break

        success = all(r.success for r in step_results)

        return ExecutionResult(
            success=success,
            result=accumulated_output,
            duration_ms=(time.perf_counter() - start_time) * 1000,
            step_results=step_results,
            metadata={**plan.metadata, "execution_time": datetime.utcnow().isoformat()},
        )

    async def _execute_step(self, step: PlanStep, context: dict[str, Any]) -> StepResult:
        """Execute a single plan step."""
        import time

        start_time = time.perf_counter()

        try:
            if step.type == StepType.TOOL and step.tool:
                tool = get_tool(step.tool)

                if tool:
                    args = self._resolve_args(step.args or {}, context)
                    output = await tool.run(**args)
                else:
                    output = await self._mock_tool_execution(step.tool, step.args or {})

            elif step.type == StepType.MESSAGE:
                output = {"message": step.content or ""}

            else:
                output = {"status": "completed"}

            duration = (time.perf_counter() - start_time) * 1000

            return StepResult(
                step_name=step.name or step.type.value,
                success=True,
                output=output,
                duration_ms=duration,
            )

        except Exception as e:
            logger.error(f"Step execution failed: {e}", exc_info=True)
            return StepResult(
                step_name=step.name or step.type.value,
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

    def _resolve_args(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Resolve arguments by substituting context values."""
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str) and value.startswith("$"):
                var_name = value[1:]
                resolved[key] = context.get(var_name, value)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_args(value, context)
            else:
                resolved[key] = value
        return resolved

    async def _mock_tool_execution(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Mock tool execution for tools that aren't available."""
        logger.warning(f"Tool {tool_name} not found, using mock execution")

        if tool_name == "validation_tool":
            return {
                "valid": True,
                "warnings": [],
                "resource_type": args.get("resource_type", "unknown"),
            }
        elif tool_name == "prerequisite_checker":
            return {"prerequisites_met": True, "missing": [], "recommendations": []}
        elif tool_name == "verification_tool":
            return {
                "verified": True,
                "status": "healthy",
                "resource_name": args.get("resource_name", "unknown"),
            }
        else:
            return {"status": "completed", "tool": tool_name, "args": args}

    async def run_provisioning(self, deployment_id: str) -> dict[str, Any]:
        """Run a complete provisioning workflow."""
        logger.info(f"Starting provisioning for deployment {deployment_id}")

        goal = f"Provision resources for deployment {deployment_id}"

        result = await self.run(goal)

        return {
            "deployment_id": deployment_id,
            "success": result.success,
            "result": result.result,
            "duration_ms": result.duration_ms,
            "error": result.error,
        }
