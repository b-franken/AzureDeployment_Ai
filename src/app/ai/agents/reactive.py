from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, DefaultDict

from app.ai.agents.base import Agent
from app.ai.agents.types import AgentContext, ExecutionPlan, ExecutionResult, PlanStep, StepType


class EventType(Enum):
    DEPLOYMENT_COMPLETE = "deployment_complete"
    RESOURCE_FAILURE = "resource_failure"
    COST_THRESHOLD = "cost_threshold"
    SECURITY_ALERT = "security_alert"
    STATUS = "status"


@dataclass(slots=True)
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    sequence: int = 0


Handler = Callable[[Event], Awaitable[None]]


class ReactiveAgent(Agent[dict[str, Any], dict[str, Any]]):
    def __init__(self, context: AgentContext | None = None):
        super().__init__(context)
        self._handlers: DefaultDict[EventType,
                                    list[Handler]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._workers: set[asyncio.Task[None]] = set()
        self._running: bool = False

    def on(self, event_type: EventType, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def off(self, event_type: EventType, handler: Handler) -> None:
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
            except ValueError:
                pass

    async def emit(self, event: Event) -> None:
        await self._queue.put(event)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        workers = max(1, int(self.context.max_parallel_tasks))
        for _ in range(workers):
            task = asyncio.create_task(
                self._run_worker(), name="reactive_worker")
            self._workers.add(task)
            task.add_done_callback(self._workers.discard)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for task in list(self._workers):
            task.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def _run_worker(self) -> None:
        try:
            while self._running:
                event = await self._queue.get()
                handlers = list(self._handlers.get(event.type, []))
                for h in handlers:
                    try:
                        await h(event)
                    except Exception:
                        pass
                self._queue.task_done()
        except asyncio.CancelledError:
            return

    async def plan(self, goal: str) -> ExecutionPlan:
        step = PlanStep(type=StepType.MESSAGE, name="reactive_runtime",
                        description="Start reactive loop")
        return ExecutionPlan(steps=[step], metadata={"goal": goal})

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        await self.start()
        return ExecutionResult(success=True, result={}, metadata={"started": True})


__all__ = ["ReactiveAgent", "Event", "EventType"]
