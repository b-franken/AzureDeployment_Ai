from __future__ import annotations
import json
from typing import Any
from dataclasses import dataclass, field
from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepType
from app.memory.storage import get_async_store


@dataclass
class Experience:
    goal: str
    plan: ExecutionPlan
    result: ExecutionResult
    feedback: float
    metadata: dict[str, Any] = field(default_factory=dict)


class LearningAgent(Agent[list[Experience], dict[str, Any]]):
    def __init__(self, context: AgentContext | None = None):
        super().__init__(context)
        self.experiences: list[Experience] = []
        self.strategies: dict[str, float] = {}
        self.exploration_rate = 0.1

    async def plan(self, goal: str) -> ExecutionPlan:
        similar_experiences = await self._find_similar_experiences(goal)

        if similar_experiences and self._should_exploit():
            best_experience = max(similar_experiences,
                                  key=lambda e: e.feedback)
            return self._adapt_plan(best_experience.plan, goal)
        else:
            return await self._explore_new_strategy(goal)

    def _should_exploit(self) -> bool:
        import random
        return random.random() > self.exploration_rate

    async def _find_similar_experiences(self, goal: str) -> list[Experience]:
        store = await get_async_store()

        stored_experiences = await store.search_messages(
            user_id=f"learning_agent_{self.context.user_id}",
            query=goal[:50],
            limit=10
        )

        experiences = []
        for exp_data in stored_experiences:
            try:
                content = json.loads(exp_data["content"])
                experience = Experience(
                    goal=content["goal"],
                    plan=ExecutionPlan(**content["plan"]),
                    result=ExecutionResult(**content["result"]),
                    feedback=content["feedback"]
                )
                experiences.append(experience)
            except Exception:
                continue

        return experiences

    def _adapt_plan(self, base_plan: ExecutionPlan, new_goal: str) -> ExecutionPlan:
        adapted_steps = []

        for step in base_plan.steps:
            adapted_step = PlanStep(
                type=step.type,
                name=step.name,
                tool=step.tool,
                args={**step.args} if step.args else None,
                dependencies=step.dependencies.copy()
            )

            if adapted_step.args and "goal" in adapted_step.args:
                adapted_step.args["goal"] = new_goal

            adapted_steps.append(adapted_step)

        return ExecutionPlan(
            steps=adapted_steps,
            metadata={
                "adapted_from": base_plan.metadata,
                "new_goal": new_goal
            }
        )

    async def _explore_new_strategy(self, goal: str) -> ExecutionPlan:
        from app.ai.generator import generate_response

        strategy_prompt = f"""
        Generate a new strategy for: {goal}
        
        Consider different approaches and be creative.
        """

        response = await generate_response(
            strategy_prompt,
            memory=[],
            provider="openai"
        )

        steps = self._parse_strategy_response(response, goal)

        return ExecutionPlan(
            steps=steps,
            metadata={"strategy": "exploration", "goal": goal}
        )

    def _parse_strategy_response(self, response: str, goal: str) -> list[PlanStep]:
        steps = []

        if "analyze" in response.lower():
            steps.append(
                PlanStep(
                    type=StepType.TOOL,
                    name="analysis",
                    tool="analysis_tool",
                    args={"target": goal}
                )
            )

        steps.append(
            PlanStep(
                type=StepType.TOOL,
                name="execute",
                tool="provision_orchestrator",
                args={"request": goal},
                dependencies=["analysis"] if any(
                    s.name == "analysis" for s in steps) else []
            )
        )

        return steps

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        result = await super().execute(plan)

        feedback = self._calculate_feedback(result)

        experience = Experience(
            goal=plan.metadata.get("goal", ""),
            plan=plan,
            result=result,
            feedback=feedback
        )

        await self._store_experience(experience)
        self._update_strategies(experience)

        result.metadata["feedback"] = feedback
        result.metadata["learning"] = {
            "total_experiences": len(self.experiences),
            "exploration_rate": self.exploration_rate
        }

        return result

    def _calculate_feedback(self, result: ExecutionResult) -> float:
        if not result.success:
            return -1.0

        base_score = 1.0

        if result.duration_ms < 1000:
            base_score += 0.2
        elif result.duration_ms > 5000:
            base_score -= 0.2

        success_rate = sum(
            1 for sr in result.step_results if sr.success) / max(len(result.step_results), 1)
        base_score *= success_rate

        return min(max(base_score, -1.0), 1.0)

    async def _store_experience(self, experience: Experience) -> None:
        store = await get_async_store()

        content = {
            "goal": experience.goal,
            "plan": experience.plan.__dict__,
            "result": {
                "success": experience.result.success,
                "duration_ms": experience.result.duration_ms,
                "metadata": experience.result.metadata
            },
            "feedback": experience.feedback
        }

        await store.store_message(
            user_id=f"learning_agent_{self.context.user_id}",
            role="system",
            content=json.dumps(content),
            metadata={"type": "experience"}
        )

        self.experiences.append(experience)

        if len(self.experiences) > 100:
            self.experiences = self.experiences[-100:]

    def _update_strategies(self, experience: Experience) -> None:
        strategy_key = experience.plan.metadata.get("strategy", "default")

        if strategy_key not in self.strategies:
            self.strategies[strategy_key] = 0.0

        alpha = 0.1
        self.strategies[strategy_key] = (
            alpha * experience.feedback +
            (1 - alpha) * self.strategies[strategy_key]
        )

        if experience.feedback > 0.5:
            self.exploration_rate = max(0.01, self.exploration_rate * 0.95)
        else:
            self.exploration_rate = min(0.3, self.exploration_rate * 1.05)
