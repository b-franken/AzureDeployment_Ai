from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepResult, StepType
from app.core.logging import get_logger

logger = get_logger(__name__)


class EventType(Enum):
    DEPLOYMENT_STARTED = "deployment_started"
    DEPLOYMENT_COMPLETE = "deployment_complete"
    DEPLOYMENT_FAILED = "deployment_failed"
    RESOURCE_CREATED = "resource_created"
    RESOURCE_UPDATED = "resource_updated"
    RESOURCE_DELETED = "resource_deleted"
    RESOURCE_FAILURE = "resource_failure"
    COST_THRESHOLD = "cost_threshold"
    SECURITY_ALERT = "security_alert"
    HEALTH_CHECK = "health_check"


@dataclass
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str | None = None
    correlation_id: str | None = None


EventHandler = Callable[[Event], Awaitable[None]]


class ReactiveAgent(Agent[dict[str, Any], dict[str, Any]]):
    def __init__(self, context: AgentContext | None = None):
        super().__init__(context)
        self.event_handlers: dict[EventType, list[EventHandler]] = {}
        self.event_queue: asyncio.Queue[Event] = asyncio.Queue()
        self._running = False
        self._worker_task: asyncio.Task | None = None

    def on(self, event_type: EventType, handler: EventHandler) -> None:
        """Register an event handler for a specific event type."""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)

    def off(self, event_type: EventType, handler: EventHandler) -> None:
        """Unregister an event handler."""
        if event_type in self.event_handlers:
            try:
                self.event_handlers[event_type].remove(handler)
            except ValueError:
                pass

    async def emit(self, event: Event) -> None:
        """Emit an event to be processed."""
        await self.event_queue.put(event)

    async def start(self) -> None:
        """Start the event processing loop."""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._process_events())
        logger.info("ReactiveAgent started")

    async def stop(self) -> None:
        """Stop the event processing loop."""
        self._running = False

        if self._worker_task:
            await self.emit(Event(type=EventType.HEALTH_CHECK, payload={"stop": True}))

            try:
                await asyncio.wait_for(self._worker_task, timeout=5.0)
            except TimeoutError:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass

            self._worker_task = None

        logger.info("ReactiveAgent stopped")

    async def _process_events(self) -> None:
        """Main event processing loop."""
        while self._running:
            try:
                event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)

                if event.payload.get("stop") and event.type == EventType.HEALTH_CHECK:
                    break

                await self._handle_event(event)

            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing event: {e}", exc_info=True)

    async def _handle_event(self, event: Event) -> None:
        """Handle a single event by calling all registered handlers."""
        async with self.tracer.trace_operation(
            "handle_event",
            {
                "event.type": event.type.value,
                "event.source": event.source or "unknown",
                "event.correlation_id": event.correlation_id or "none",
            }
        ) as span:
            handlers = self.event_handlers.get(event.type, [])
            span.set_attribute("handlers_count", len(handlers))

            if not handlers:
                logger.debug(f"No handlers registered for event type: {event.type}")
                span.set_attribute("result", "no_handlers")
                return

            async with self.tracer.trace_operation(
                "execute_handlers",
                {"handlers_count": len(handlers)}
            ):
                tasks = [self._safe_handler_call(handler, event) for handler in handlers]
                results = await asyncio.gather(*tasks, return_exceptions=True)

            failed_count = 0
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    failed_count += 1
                    logger.error(
                        f"Handler {handlers[i].__name__} failed for event {event.type}: {result}",
                        exc_info=result,
                    )
            
            span.set_attribute("handlers.executed", len(handlers))
            span.set_attribute("handlers.failed", failed_count)
            span.set_attribute("result", "completed" if failed_count == 0 else "partial_failure")

    async def _safe_handler_call(self, handler: EventHandler, event: Event) -> None:
        """Safely call an event handler with error handling."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Event handler {handler.__name__} raised exception: {e}")
            raise

    async def plan(self, goal: str) -> ExecutionPlan:
        """Plan reactive monitoring based on the goal."""
        steps = []

        if "monitor" in goal.lower():
            steps.append(
                PlanStep(
                    type=StepType.TOOL,
                    name="setup_monitoring",
                    description="Set up event monitoring",
                    tool="monitoring_setup",
                    args={"goal": goal},
                )
            )

        if "alert" in goal.lower():
            steps.append(
                PlanStep(
                    type=StepType.TOOL,
                    name="configure_alerts",
                    description="Configure alert rules",
                    tool="alert_configuration",
                    args={"goal": goal},
                )
            )

        return ExecutionPlan(steps=steps, metadata={"reactive": True, "goal": goal})

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult[dict[str, Any]]:
        """Execute the reactive monitoring plan."""
        import time

        start_time = time.perf_counter()

        await self.start()

        step_results = []

        for step in plan.steps:
            try:
                if step.type == StepType.TOOL:
                    await asyncio.sleep(0.1)

                    step_results.append(
                        StepResult(
                            step_name=step.name or "unknown",
                            success=True,
                            output={"status": "configured", "step": step.name},
                        )
                    )
            except Exception as e:
                step_results.append(
                    StepResult(step_name=step.name or "unknown", success=False, error=str(e))
                )

        success = all(r.success for r in step_results)

        return ExecutionResult(
            success=success,
            result={
                "monitoring_active": self._running,
                "registered_handlers": {
                    event_type.value: len(handlers)
                    for event_type, handlers in self.event_handlers.items()
                },
            },
            duration_ms=(time.perf_counter() - start_time) * 1000,
            step_results=step_results,
        )
