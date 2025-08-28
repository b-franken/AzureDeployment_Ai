from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.logging import get_logger
from app.observability.agent_service_mapper import get_agent_service_name

logger = get_logger(__name__)


class AgentTracer:
    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self.service_name = get_agent_service_name(agent_name)
        self.tracer = trace.get_tracer(self.service_name)

    @asynccontextmanager
    async def trace_operation(
        self,
        operation_name: str,
        attributes: dict[str, Any] | None = None,
        parent_span: trace.Span | None = None,
    ) -> AsyncGenerator[trace.Span, None]:
        span_attributes = {
            "agent.name": self.agent_name,
            "agent.operation": operation_name,
            "component": "ai_agent",
        }
        if attributes:
            span_attributes.update(attributes)

        with self.tracer.start_as_current_span(
            f"{self.agent_name}.{operation_name}",
            attributes=span_attributes,
        ) as span:
            span.set_attribute("agent.start_time", time.time())
            try:
                yield span
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                logger.error(
                    "Agent operation failed",
                    agent=self.agent_name,
                    operation=operation_name,
                    error=str(exc),
                    exc_info=True,
                )
                raise
            finally:
                span.set_attribute("agent.end_time", time.time())

    @asynccontextmanager
    async def trace_agent_call(
        self,
        target_agent: str,
        method: str,
        request_data: dict[str, Any] | None = None,
    ) -> AsyncGenerator[trace.Span, None]:
        span_attributes = {
            "agent.caller": self.agent_name,
            "agent.target": target_agent,
            "agent.method": method,
            "component": "agent_communication",
            "operation.type": "agent_call",
        }

        if request_data:
            span_attributes["request.size"] = len(str(request_data))
            if "goal" in request_data:
                span_attributes["request.goal"] = str(request_data["goal"])[:200]

        with self.tracer.start_as_current_span(
            f"{self.agent_name} → {target_agent}",
            attributes=span_attributes,
        ) as span:
            try:
                yield span
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                logger.error(
                    "Agent call failed",
                    caller=self.agent_name,
                    target=target_agent,
                    method=method,
                    error=str(exc),
                    exc_info=True,
                )
                raise

    def track_agent_metrics(
        self,
        operation: str,
        duration_ms: float,
        success: bool,
        resource_count: int = 0,
    ) -> None:
        span = trace.get_current_span()
        if span:
            span.set_attribute("agent.operation.duration_ms", duration_ms)
            span.set_attribute("agent.operation.success", success)
            span.set_attribute("agent.operation.resource_count", resource_count)

        logger.info(
            "Agent operation completed",
            agent=self.agent_name,
            operation=operation,
            duration_ms=duration_ms,
            success=success,
            resource_count=resource_count,
        )

    def create_dependency_span(
        self,
        dependency_type: str,
        target: str,
        operation: str,
        data: dict[str, Any] | None = None,
    ) -> trace.Span:
        span_attributes = {
            "dependency.type": dependency_type,
            "dependency.target": target,
            "dependency.operation": operation,
            "agent.name": self.agent_name,
        }
        
        if data:
            span_attributes.update({f"dependency.{k}": v for k, v in data.items()})

        return self.tracer.start_span(
            f"{dependency_type}:{target}",
            attributes=span_attributes,
        )


class AgentTracingManager:
    _tracers: dict[str, AgentTracer] = {}

    @classmethod
    def get_tracer(cls, agent_name: str) -> AgentTracer:
        if agent_name not in cls._tracers:
            cls._tracers[agent_name] = AgentTracer(agent_name)
            logger.debug(f"Created tracer for agent: {agent_name}")
        return cls._tracers[agent_name]

    @classmethod
    def trace_agent_interaction(
        cls,
        caller_agent: str,
        target_agent: str,
        operation: str,
        data: dict[str, Any] | None = None,
    ) -> trace.Span:
        caller_tracer = cls.get_tracer(caller_agent)
        
        span_attributes = {
            "interaction.type": "agent_to_agent",
            "interaction.caller": caller_agent,
            "interaction.target": target_agent,
            "interaction.operation": operation,
        }
        
        if data:
            span_attributes.update({f"interaction.{k}": v for k, v in data.items()})

        return caller_tracer.tracer.start_span(
            f"{caller_agent} ⟷ {target_agent}",
            attributes=span_attributes,
        )

    @classmethod
    def clear_tracers(cls) -> None:
        cls._tracers.clear()
        logger.debug("Cleared all agent tracers")


def get_agent_tracer(agent_name: str) -> AgentTracer:
    return AgentTracingManager.get_tracer(agent_name)