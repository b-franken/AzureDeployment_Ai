from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepResult, StepType


@dataclass
class ChainLink:
    name: str
    processor: Callable[[Any], Awaitable[Any]]
    condition: Callable[[Any], bool] | None = None
    error_handler: Callable[[Exception], Awaitable[Any]] | None = None
    transform: Callable[[Any], Any] | None = None


class ChainAgent(Agent[list[ChainLink], Any]):
    def __init__(self, context: AgentContext | None = None):
        super().__init__(context)
        self.links: list[ChainLink] = []
        self._middleware: list[Callable[[Any], Awaitable[Any]]] = []

    def add_link(self, link: ChainLink) -> ChainAgent:
        self.links.append(link)
        return self

    def use(self, middleware: Callable[[Any], Awaitable[Any]]) -> ChainAgent:
        self._middleware.append(middleware)
        return self

    async def plan(self, goal: str) -> ExecutionPlan:
        steps = []

        for link in self.links:
            step = PlanStep(
                type=StepType.SEQUENTIAL, name=link.name, description=f"Process: {link.name}"
            )
            steps.append(step)

        return ExecutionPlan(steps=steps, metadata={"chain_length": len(self.links)})

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[Any]:
        import time

        start_time = time.perf_counter()

        current_value = plan.metadata.get("initial_value", {})
        step_results = []

        try:
            for middleware in self._middleware:
                current_value = await middleware(current_value)

            for link in self.links:
                if link.condition and not link.condition(current_value):
                    continue

                try:
                    result = await link.processor(current_value)

                    if link.transform:
                        result = link.transform(result)

                    current_value = result

                    step_results.append(
                        StepResult(step_name=link.name, success=True, output=result)
                    )

                except Exception as e:
                    if link.error_handler:
                        current_value = await link.error_handler(e)
                        step_results.append(
                            StepResult(
                                step_name=link.name,
                                success=True,
                                output=current_value,
                                error=f"Handled: {e!s}",
                            )
                        )
                    else:
                        raise

            return ExecutionResult(
                success=True,
                result=current_value,
                duration_ms=(time.perf_counter() - start_time) * 1000,
                step_results=step_results,
            )

        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            return ExecutionResult(
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - start_time) * 1000,
                step_results=step_results,
            )
