from __future__ import annotations

from typing import Any

from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.orchestrator import OrchestrationAgent
from app.ai.agents.provisioning import ProvisioningAgent
from app.ai.agents.reactive import Event, EventType, ReactiveAgent
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepType


class CoordinatorAgent(Agent[dict[str, Any], dict[str, Any]]):
    def __init__(self, context: AgentContext | None = None):
        super().__init__(context)
        self.orchestrator = OrchestrationAgent(context)
        self.reactive = ReactiveAgent(context)
        self._setup_event_handlers()

    async def _plan_coordination(self, goal: str) -> ExecutionPlan:
        from app.ai.generator import generate_response

        analysis = await generate_response(
            f"Analyze this coordination request and identify sub-tasks: {goal}",
            provider="openai",
            user_id=self.context.user_id,
        )

        steps = []
        if "provision" in analysis.lower():
            steps.append(
                PlanStep(
                    type=StepType.TOOL,
                    name="provision_task",
                    tool="provision_orchestrator",
                    args={"request": goal},
                )
            )

        if "monitor" in analysis.lower():
            steps.append(
                PlanStep(
                    type=StepType.MESSAGE,
                    name="setup_monitoring",
                    content="Setting up monitoring",
                    dependencies=(["provision_task"] if "provision_task" in [
                                  s.name for s in steps] else []),
                )
            )

        return ExecutionPlan(steps=steps)
