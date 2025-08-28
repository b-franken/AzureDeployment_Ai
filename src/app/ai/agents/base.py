from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from app.ai.agents.types import ExecutionPlan, ExecutionResult
from app.observability.agent_tracing import get_agent_tracer

TState = TypeVar("TState")
TResult = TypeVar("TResult")


@dataclass
class AgentContext:
    user_id: str | None = None
    thread_id: str | None = None
    agent_name: str | None = None
    environment: str | None = None
    dry_run: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentStatus(Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentMetrics:
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    average_planning_time_ms: float = 0.0
    average_execution_time_ms: float = 0.0
    last_execution_time: datetime | None = None


class Agent(ABC, Generic[TState, TResult]):
    def __init__(self, context: AgentContext | None = None):
        self.context = context or AgentContext()
        self.status = AgentStatus.IDLE
        self.metrics = AgentMetrics()
        self._state: TState | None = None
        self.tracer = get_agent_tracer(self.__class__.__name__)

    @abstractmethod
    async def plan(self, goal: str) -> ExecutionPlan:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[TResult]:
        raise NotImplementedError

    async def run(self, goal: str) -> ExecutionResult[TResult]:
        async with self.tracer.trace_operation(
            "run",
            {
                "agent.goal": goal[:200],
                "agent.status": self.status.value,
                "user.id": self.context.user_id or "system",
            },
        ) as span:
            self.status = AgentStatus.PLANNING
            planning_start = time.perf_counter()
            try:
                async with self.tracer.trace_operation("plan", {"goal": goal[:100]}):
                    plan = await self.plan(goal)
                planning_time = (time.perf_counter() - planning_start) * 1000
                
                self.status = AgentStatus.EXECUTING
                execution_start = time.perf_counter()
                async with self.tracer.trace_operation(
                    "execute", 
                    {"plan.steps": len(plan.steps) if hasattr(plan, 'steps') else 0}
                ):
                    result = await self.execute(plan)
                execution_time = (time.perf_counter() - execution_start) * 1000
                
                self._update_metrics(
                    success=result.success, planning_time=planning_time, execution_time=execution_time
                )
                self.status = AgentStatus.COMPLETED if result.success else AgentStatus.FAILED
                
                self.tracer.track_agent_metrics(
                    "run", planning_time + execution_time, result.success
                )
                span.set_attribute("result.success", result.success)
                span.set_attribute("planning_time_ms", planning_time)
                span.set_attribute("execution_time_ms", execution_time)
                
            except (RuntimeError, ValueError, TypeError, AttributeError) as e:
                self.status = AgentStatus.FAILED
                self._update_metrics(success=False)
                span.set_attribute("result.success", False)
                span.set_attribute("error.message", str(e))
                return ExecutionResult(success=False, error=str(e), execution_time=datetime.utcnow())
            else:
                return result

    def _update_metrics(
        self, success: bool, planning_time: float | None = None, execution_time: float | None = None
    ) -> None:
        self.metrics.total_executions += 1
        if success:
            self.metrics.successful_executions += 1
        else:
            self.metrics.failed_executions += 1
        if planning_time is not None:
            alpha = 0.1
            self.metrics.average_planning_time_ms = (
                alpha * planning_time + (1 - alpha) * self.metrics.average_planning_time_ms
            )
        if execution_time is not None:
            alpha = 0.1
            self.metrics.average_execution_time_ms = (
                alpha * execution_time + (1 - alpha) * self.metrics.average_execution_time_ms
            )
        self.metrics.last_execution_time = datetime.utcnow()

    async def cancel(self) -> None:
        self.status = AgentStatus.CANCELLED

    @property
    def state(self) -> TState | None:
        return self._state

    @state.setter
    def state(self, value: TState) -> None:
        self._state = value
