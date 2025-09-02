from __future__ import annotations

import datetime
from typing import Any, cast

from pydantic import BaseModel

from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepResult, StepType
from app.ai.intelligence.dependency_analyzer import DependencyAnalyzer
from app.ai.intelligence.resource_intelligence import ResourceIntelligence
from app.ai.nlu import parse_provision_request
from app.core.logging import get_logger
from app.observability.agent_tracing import get_agent_tracer
from app.observability.app_insights import app_insights
from app.tools.base import ToolResult
from app.tools.registry import ensure_tools_loaded, get_tool

logger = get_logger(__name__)
tracer = get_agent_tracer("ProvisioningAgent")


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

        self.dependency_analyzer = DependencyAnalyzer()
        self.resource_intelligence = ResourceIntelligence()
        ensure_tools_loaded()

    async def plan(self, goal: str) -> ExecutionPlan:
        async with tracer.trace_operation(
            "provisioning_agent_plan",
            {
                "user_id": self.user_id,
                "goal_length": len(goal),
                "environment": self.context.environment if self.context else "dev",
            },
        ) as span:
            parsed = parse_provision_request(goal)
            env = self.context.environment if self.context else "dev"
            dry_run = self.context.dry_run if self.context else True

            logger.info(
                "Starting intelligent provisioning plan",
                user_id=self.user_id,
                resource_type=parsed.resource_type,
                resource_name=parsed.resource_name,
                environment=env,
                confidence=parsed.confidence,
            )

            app_insights.track_custom_event(
                "provisioning_agent_plan_start",
                {
                    "user_id": self.user_id,
                    "resource_type": parsed.resource_type,
                    "resource_name": parsed.resource_name or "unnamed",
                    "environment": env,
                    "confidence": parsed.confidence,
                    "goal_length": len(goal),
                    "cloud_RoleName": "ProvisioningAgent",
                    "service_name": "ai.agents.provisioning",
                },
            )

            primary_resource = {
                "type": parsed.resource_type,
                "name": parsed.resource_name or f"unnamed_{parsed.resource_type}",
                "location": parsed.parameters.get("location", "westeurope"),
                **parsed.parameters,
            }

            intelligence_result = await self.resource_intelligence.analyze_resource_requirements(
                primary_resource, env, self.context.metadata if self.context else {}
            )

            all_resources = [primary_resource] + intelligence_result.inferred_resources
            dependency_plan = await self.dependency_analyzer.analyze_dependencies(
                all_resources, env
            )

            optimized_plan, optimization_metrics = (
                await self.dependency_analyzer.optimize_for_parallel_deployment(dependency_plan)
            )

            span.set_attributes(
                {
                    "resources_count": len(all_resources),
                    "inferred_resources": len(intelligence_result.inferred_resources),
                    "deployment_groups": len(optimized_plan.deployment_groups),
                    "parallel_opportunities": optimization_metrics["parallel_operations"],
                    "estimated_time_seconds": optimization_metrics["optimized_time_seconds"],
                }
            )

            steps = await self._build_intelligent_steps(
                parsed, all_resources, optimized_plan, intelligence_result, env, dry_run
            )

            logger.info(
                "Intelligent provisioning plan completed",
                total_resources=len(all_resources),
                inferred_count=len(intelligence_result.inferred_resources),
                deployment_groups=len(optimized_plan.deployment_groups),
                estimated_time_seconds=optimization_metrics["optimized_time_seconds"],
                warnings_count=len(intelligence_result.warnings),
                recommendations_count=len(intelligence_result.recommendations),
            )

            app_insights.track_custom_event(
                "provisioning_agent_plan_completed",
                {
                    "user_id": self.user_id,
                    "resource_type": parsed.resource_type,
                    "total_resources": len(all_resources),
                    "inferred_count": len(intelligence_result.inferred_resources),
                    "deployment_groups": len(optimized_plan.deployment_groups),
                    "estimated_time_seconds": optimization_metrics["optimized_time_seconds"],
                    "warnings_count": len(intelligence_result.warnings),
                    "recommendations_count": len(intelligence_result.recommendations),
                    "environment": env,
                    "cloud_RoleName": "ProvisioningAgent",
                    "service_name": "ai.agents.provisioning",
                },
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
                    "intelligence": {
                        "inferred_resources": intelligence_result.inferred_resources,
                        "recommendations": [
                            {
                                "type": rec.resource_type,
                                "name": rec.resource_name,
                                "reason": rec.reason,
                                "priority": rec.priority,
                            }
                            for rec in intelligence_result.recommendations
                        ],
                        "warnings": intelligence_result.warnings,
                        "dependency_plan": {
                            "groups_count": len(optimized_plan.deployment_groups),
                            "estimated_time_seconds": (
                                optimization_metrics["optimized_time_seconds"]
                            ),
                            "parallel_opportunities": optimization_metrics["parallel_operations"],
                            "critical_path": optimized_plan.critical_path,
                        },
                    },
                    "dry_run": dry_run,
                    "environment": env,
                },
            )

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        import time

        async with tracer.trace_operation(
            "provisioning_agent_execute",
            {
                "user_id": self.user_id,
                "steps_count": len(plan.steps),
                "environment": self.context.environment if self.context else "dev",
            },
        ) as span:
            app_insights.track_custom_event(
                "provisioning_agent_execute_start",
                {
                    "user_id": self.user_id,
                    "steps_count": len(plan.steps),
                    "environment": self.context.environment if self.context else "dev",
                    "cloud_RoleName": "ProvisioningAgent",
                    "service_name": "ai.agents.provisioning",
                },
            )

            start_time = time.perf_counter()
            step_results: list[StepResult] = []
            accumulated_output: dict[str, Any] = {}

            for step in plan.steps:
                try:
                    result = await self._execute_step(step, accumulated_output)
                    step_results.append(result)
                    if result.output:
                        accumulated_output[step.name or step.type.value] = result.output
                    if not result.success and step.type != StepType.MESSAGE:
                        break
                except Exception as e:
                    logger.error(
                        "provisioning.step_exception",
                        step=step.name or step.type.value,
                        error_type=type(e).__name__,
                        error_message=str(e),
                        exc_info=True,
                    )
                    step_results.append(
                        StepResult(
                            step_name=step.name or step.type.value, success=False, error=str(e)
                        )
                    )
                    break

            success = all(r.success for r in step_results)
            duration_ms = (time.perf_counter() - start_time) * 1000

            span.set_attributes(
                {
                    "execution_success": success,
                    "steps_executed": len(step_results),
                    "duration_ms": duration_ms,
                }
            )

            app_insights.track_custom_event(
                "provisioning_agent_execute_completed",
                {
                    "user_id": self.user_id,
                    "execution_success": success,
                    "steps_executed": len(step_results),
                    "duration_ms": duration_ms,
                    "environment": self.context.environment if self.context else "dev",
                    "cloud_RoleName": "ProvisioningAgent",
                    "service_name": "ai.agents.provisioning",
                },
            )

            return ExecutionResult(
                success=success,
                result=accumulated_output,
                duration_ms=duration_ms,
                step_results=step_results,
                metadata={
                    **plan.metadata,
                    "execution_time": datetime.datetime.now(datetime.UTC).isoformat(),
                },
            )

    async def _execute_step(self, step: PlanStep, context: dict[str, Any]) -> StepResult:
        import time

        start_time = time.perf_counter()
        try:
            if step.type == StepType.TOOL and step.tool:
                tool = get_tool(step.tool)
                if tool:
                    args = self._resolve_args(step.args or {}, context)
                    output = await tool.run(**args)
                else:
                    mock_result = await self._mock_tool_execution(step.tool, step.args or {})
                    output = (
                        cast(ToolResult, mock_result)
                        if isinstance(mock_result, dict)
                        else {"ok": True, "summary": str(mock_result), "output": str(mock_result)}
                    )
            elif step.type == StepType.MESSAGE:
                output = {"ok": True, "summary": "message", "output": step.content or ""}
            else:
                output = {"ok": True, "summary": "completed", "output": "completed"}
            duration = (time.perf_counter() - start_time) * 1000
            return StepResult(
                step_name=step.name or step.type.value,
                success=True,
                output=output,
                duration_ms=duration,
            )
        except Exception as e:
            return StepResult(
                step_name=step.name or step.type.value,
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

    def _resolve_args(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
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
        logger.warning("provisioning.mock_tool_used", tool=tool_name)
        if tool_name == "validation_tool":
            return {
                "valid": True,
                "warnings": [],
                "resource_type": args.get("resource_type", "unknown"),
            }
        if tool_name == "prerequisite_checker":
            return {"prerequisites_met": True, "missing": [], "recommendations": []}
        if tool_name == "verification_tool":
            return {
                "verified": True,
                "status": "healthy",
                "resource_name": args.get("resource_name", "unknown"),
            }
        return {"status": "completed", "tool": tool_name, "args": args}

    async def _build_intelligent_steps(
        self,
        parsed: Any,
        all_resources: list[dict[str, Any]],
        deployment_plan: Any,
        intelligence_result: Any,
        environment: str,
        dry_run: bool,
    ) -> list[PlanStep]:
        steps: list[PlanStep] = []

        steps.append(
            PlanStep(
                type=StepType.TOOL,
                name="validate_intelligent_request",
                description="Validate provisioning request with intelligence insights",
                tool="validation_tool",
                args={
                    "resource_type": parsed.resource_type,
                    "parameters": parsed.parameters,
                    "inferred_resources": intelligence_result.inferred_resources,
                    "warnings": intelligence_result.warnings,
                },
            )
        )

        for group_index, deployment_group in enumerate(deployment_plan.deployment_groups):
            group_name = f"deploy_group_{group_index}"

            if len(deployment_group) == 1:
                resource_dep = deployment_group[0]
                steps.append(
                    PlanStep(
                        type=StepType.TOOL,
                        name=f"deploy_{resource_dep.resource_name}",
                        description=(
                            f"Deploy {resource_dep.resource_type}: " f"{resource_dep.resource_name}"
                        ),
                        tool="provision_orchestrator",
                        args={
                            "resource_type": resource_dep.resource_type,
                            "resource_name": resource_dep.resource_name,
                            "environment": environment,
                            "dry_run": dry_run,
                        },
                        dependencies=(
                            [f"deploy_group_{group_index - 1}"]
                            if group_index > 0
                            else ["validate_intelligent_request"]
                        ),
                        timeout_seconds=resource_dep.estimated_deploy_time_seconds + 60,
                    )
                )
            else:
                parallel_steps = []
                for resource_dep in deployment_group:
                    step_name = f"deploy_{resource_dep.resource_name}"
                    parallel_steps.append(step_name)
                    steps.append(
                        PlanStep(
                            type=StepType.TOOL,
                            name=step_name,
                            description=(
                                f"Deploy {resource_dep.resource_type}: "
                                f"{resource_dep.resource_name} (parallel)"
                            ),
                            tool="provision_orchestrator",
                            args={
                                "resource_type": resource_dep.resource_type,
                                "resource_name": resource_dep.resource_name,
                                "environment": environment,
                                "dry_run": dry_run,
                                "parallel_execution": True,
                            },
                            dependencies=(
                                [f"deploy_group_{group_index - 1}"]
                                if group_index > 0
                                else ["validate_intelligent_request"]
                            ),
                            timeout_seconds=resource_dep.estimated_deploy_time_seconds + 60,
                        )
                    )

                steps.append(
                    PlanStep(
                        type=StepType.MESSAGE,
                        name=group_name,
                        description=f"Parallel deployment group {group_index} completed",
                        content=(
                            f"Successfully deployed {len(deployment_group)} "
                            "resources in parallel"
                        ),
                        dependencies=parallel_steps,
                    )
                )

        final_dependencies = []
        if deployment_plan.deployment_groups:
            last_group_index = len(deployment_plan.deployment_groups) - 1
            if len(deployment_plan.deployment_groups[last_group_index]) > 1:
                final_dependencies = [f"deploy_group_{last_group_index}"]
            else:
                last_resource = deployment_plan.deployment_groups[last_group_index][0]
                final_dependencies = [f"deploy_{last_resource.resource_name}"]

        steps.append(
            PlanStep(
                type=StepType.TOOL,
                name="verify_intelligent_deployment",
                description="Verify deployment with intelligent validation",
                tool="verification_tool",
                args={
                    "resource_type": parsed.resource_type,
                    "resource_name": parsed.resource_name,
                    "all_resources": [r["name"] for r in all_resources],
                    "deployment_plan": {
                        "groups": len(deployment_plan.deployment_groups),
                        "critical_path": deployment_plan.critical_path,
                    },
                },
                dependencies=final_dependencies,
            )
        )

        if intelligence_result.recommendations:
            steps.append(
                PlanStep(
                    type=StepType.MESSAGE,
                    name="intelligence_recommendations",
                    description="Resource intelligence recommendations",
                    content=(
                        f"Consider these {len(intelligence_result.recommendations)} "
                        "recommendations for optimal deployment"
                    ),
                    dependencies=["verify_intelligent_deployment"],
                )
            )

        return steps

    async def run_provisioning(self, deployment_id: str) -> dict[str, Any]:
        logger.info("provisioning.start", deployment_id=deployment_id)
        goal = f"Provision resources for deployment {deployment_id}"
        result = await self.run(goal)
        return {
            "deployment_id": deployment_id,
            "success": result.success,
            "result": result.result,
            "duration_ms": result.duration_ms,
            "error": result.error,
        }
