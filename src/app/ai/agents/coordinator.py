from __future__ import annotations
from typing import Any
from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.orchestrator import OrchestrationAgent
from app.ai.agents.provisioning import ProvisioningAgent
from app.ai.agents.reactive import ReactiveAgent, Event, EventType
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepType, StepResult


class CoordinatorAgent(Agent[dict[str, Any], dict[str, Any]]):
    def __init__(self, context: AgentContext | None = None):
        super().__init__(context)
        self.orchestrator = OrchestrationAgent(context)
        self.reactive = ReactiveAgent(context)
        self._setup_event_handlers()

    def _setup_event_handlers(self) -> None:
        self.reactive.on(
            EventType.DEPLOYMENT_COMPLETE,
            self._handle_deployment_complete
        )

        self.reactive.on(
            EventType.RESOURCE_FAILURE,
            self._handle_resource_failure
        )

    async def _handle_deployment_complete(self, event: Event) -> None:
        verification_goal = f"Verify deployment {event.payload.get('deployment_id')}"
        plan = await self.orchestrator.plan(verification_goal)
        await self.orchestrator.execute(plan)

    async def _handle_resource_failure(self, event: Event) -> None:
        recovery_goal = f"Recover failed resource {event.payload.get('resource_id')}"
        plan = await self.orchestrator.plan(recovery_goal)
        await self.orchestrator.execute(plan)

    async def plan(self, goal: str) -> ExecutionPlan:
        if "coordinate" in goal.lower():
            return await self._plan_coordination(goal)
        elif "provision" in goal.lower():
            agent = ProvisioningAgent(
                user_id=self.context.user_id,
                context=self.context
            )
            return await agent.plan(goal)
        else:
            return await self.orchestrator.plan(goal)

    async def _plan_coordination(self, goal: str) -> ExecutionPlan:
        from app.ai.generator import generate_response

        analysis = await generate_response(
            f"Analyze this coordination request and identify sub-tasks: {goal}",
            memory=[],
            provider="openai"
        )

        steps = []

        if "provision" in analysis.lower():
            steps.append(
                PlanStep(
                    type=StepType.TOOL,
                    name="provision_task",
                    tool="provision_orchestrator",
                    args={"request": goal}
                )
            )

        if "monitor" in analysis.lower():
            steps.append(
                PlanStep(
                    type=StepType.MESSAGE,
                    name="setup_monitoring",
                    content="Setting up monitoring",
                    dependencies=["provision_task"] if "provision_task" in [
                        s.name for s in steps] else []
                )
            )

        return ExecutionPlan(steps=steps)

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        await self.reactive.start()

        try:
            main_result = await self.orchestrator.execute(plan)

            if main_result.success:
                await self.reactive.emit(
                    Event(
                        type=EventType.DEPLOYMENT_COMPLETE,
                        payload={
                            "deployment_id": main_result.metadata.get("deployment_id"),
                            "result": main_result.result
                        }
                    )
                )

            return main_result

        finally:
            await self.reactive.stop()

    def register_agent(self, name: str, agent: Agent) -> None:
        self.orchestrator.register_agent(name, agent)
