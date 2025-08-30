from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, UTC
from typing import Any, Dict, Optional, AsyncIterator
from dataclasses import dataclass

from opentelemetry import trace, propagate
from opentelemetry.trace import Status, StatusCode, SpanKind
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.propagators.composite import CompositeHTTPPropagator

from app.core.logging import get_logger
from app.observability.app_insights import app_insights

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)

propagator = CompositeHTTPPropagator([
    TraceContextTextMapPropagator(),
    W3CBaggagePropagator()
])


@dataclass
class ServiceBoundary:
    service_name: str
    operation_name: str
    correlation_id: str
    user_id: Optional[str] = None
    span_context: Optional[Dict[str, str]] = None
    metadata: Optional[Dict[str, Any]] = None


class DistributedTracer:
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.logger = logger.bind(service=service_name)
    
    @asynccontextmanager
    async def start_distributed_span(
        self,
        operation_name: str,
        correlation_id: str,
        parent_context: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
        span_kind: SpanKind = SpanKind.INTERNAL,
        attributes: Optional[Dict[str, Any]] = None
    ) -> AsyncIterator[trace.Span]:
        
        context = trace.set_span_in_context(trace.INVALID_SPAN)
        if parent_context:
            context = propagator.extract(parent_context)
        
        with tracer.start_as_current_span(
            f"{self.service_name}.{operation_name}",
            context=context,
            kind=span_kind,
            attributes={
                "service.name": self.service_name,
                "operation.name": operation_name,
                "correlation.id": correlation_id,
                "user.id": user_id or "system",
                **(attributes or {})
            }
        ) as span:
            boundary = ServiceBoundary(
                service_name=self.service_name,
                operation_name=operation_name,
                correlation_id=correlation_id,
                user_id=user_id,
                span_context=self.extract_span_context(span),
                metadata=attributes or {}
            )
            
            span.set_attribute("boundary.service", self.service_name)
            span.set_attribute("boundary.operation", operation_name)
            
            start_time = time.perf_counter()
            
            try:
                self.logger.info(
                    "distributed_span_started",
                    operation=operation_name,
                    correlation_id=correlation_id,
                    trace_id=format(span.get_span_context().trace_id, '032x'),
                    span_id=format(span.get_span_context().span_id, '016x')
                )
                
                yield span
                
                duration = (time.perf_counter() - start_time) * 1000
                span.set_attribute("operation.duration_ms", duration)
                span.set_status(Status(StatusCode.OK))
                
                self.track_service_boundary_crossing(boundary, success=True, duration_ms=duration)
                
                self.logger.info(
                    "distributed_span_completed",
                    operation=operation_name,
                    correlation_id=correlation_id,
                    duration_ms=duration,
                    success=True
                )
                
            except Exception as e:
                duration = (time.perf_counter() - start_time) * 1000
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("operation.duration_ms", duration)
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("error.message", str(e))
                
                self.track_service_boundary_crossing(boundary, success=False, duration_ms=duration, error=str(e))
                
                self.logger.error(
                    "distributed_span_failed",
                    operation=operation_name,
                    correlation_id=correlation_id,
                    duration_ms=duration,
                    error=str(e),
                    exc_info=True
                )
                
                raise
    
    def extract_span_context(self, span: trace.Span) -> Dict[str, str]:
        carrier = {}
        propagator.inject(carrier)
        return carrier
    
    def create_child_context(self, correlation_id: str, operation_name: str, user_id: Optional[str] = None) -> Dict[str, str]:
        context = self.extract_span_context(trace.get_current_span())
        context.update({
            "x-correlation-id": correlation_id,
            "x-user-id": user_id or "system",
            "x-operation": f"{self.service_name}.{operation_name}",
            "x-service": self.service_name
        })
        return context
    
    def track_service_boundary_crossing(
        self,
        boundary: ServiceBoundary,
        success: bool,
        duration_ms: float,
        error: Optional[str] = None
    ) -> None:
        try:
            app_insights.track_custom_event(
                "service_boundary_crossed",
                {
                    "service_name": str(boundary.service_name),
                    "operation_name": str(boundary.operation_name),
                    "correlation_id": str(boundary.correlation_id),
                    "user_id": str(boundary.user_id or "system"),
                    "success": str(success).lower(),
                    "error": str(error) if error else "none",
                    "timestamp": datetime.now(UTC).isoformat()
                },
                {
                    "duration_ms": duration_ms,
                    "success_flag": int(success)
                }
            )
            
            app_insights.track_dependency(
                name=f"{boundary.service_name}.{boundary.operation_name}",
                data=json.dumps(boundary.metadata or {}),
                type_name="internal_service",
                target=boundary.service_name,
                duration=int(duration_ms),
                success=success,
                result_code="200" if success else "500",
                properties={
                    "correlation_id": str(boundary.correlation_id),
                    "user_id": str(boundary.user_id or "system"),
                    "operation": str(boundary.operation_name)
                }
            )
            
        except Exception as e:
            self.logger.warning(
                "failed_to_track_service_boundary",
                service=boundary.service_name,
                operation=boundary.operation_name,
                error=str(e)
            )


class ServiceRegistry:
    _tracers: Dict[str, DistributedTracer] = {}
    
    @classmethod
    def get_tracer(cls, service_name: str) -> DistributedTracer:
        if service_name not in cls._tracers:
            cls._tracers[service_name] = DistributedTracer(service_name)
        return cls._tracers[service_name]
    
    @classmethod
    def register_service(cls, service_name: str) -> DistributedTracer:
        return cls.get_tracer(service_name)


class CrossServiceTracer:
    def __init__(self):
        self.registry = ServiceRegistry()
    
    async def trace_cross_service_call(
        self,
        from_service: str,
        to_service: str,
        operation: str,
        correlation_id: str,
        user_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        
        from_tracer = self.registry.get_tracer(from_service)
        
        context = from_tracer.create_child_context(correlation_id, f"call_{to_service}_{operation}", user_id)
        
        async with from_tracer.start_distributed_span(
            f"cross_service_call_{to_service}_{operation}",
            correlation_id,
            user_id=user_id,
            span_kind=SpanKind.CLIENT,
            attributes={
                "target.service": to_service,
                "target.operation": operation,
                "payload.size": len(json.dumps(payload or {}))
            }
        ) as span:
            span.set_attribute("cross_service.from", from_service)
            span.set_attribute("cross_service.to", to_service)
            span.set_attribute("cross_service.operation", operation)
            
            logger.info(
                "cross_service_call_initiated",
                from_service=from_service,
                to_service=to_service,
                operation=operation,
                correlation_id=correlation_id
            )
            
            return context
    
    async def receive_cross_service_call(
        self,
        service_name: str,
        operation: str,
        correlation_id: str,
        parent_context: Dict[str, str],
        user_id: Optional[str] = None
    ) -> AsyncIterator[trace.Span]:
        
        tracer = self.registry.get_tracer(service_name)
        
        async with tracer.start_distributed_span(
            f"handle_{operation}",
            correlation_id,
            parent_context=parent_context,
            user_id=user_id,
            span_kind=SpanKind.SERVER,
            attributes={
                "handler.service": service_name,
                "handler.operation": operation,
                "received.from": parent_context.get("x-service", "unknown")
            }
        ) as span:
            span.set_attribute("cross_service.received", True)
            span.set_attribute("cross_service.from_service", parent_context.get("x-service", "unknown"))
            
            logger.info(
                "cross_service_call_received",
                service=service_name,
                operation=operation,
                correlation_id=correlation_id,
                from_service=parent_context.get("x-service", "unknown")
            )
            
            yield span


_cross_service_tracer = CrossServiceTracer()


def get_service_tracer(service_name: str) -> DistributedTracer:
    return ServiceRegistry.get_tracer(service_name)


def get_cross_service_tracer() -> CrossServiceTracer:
    return _cross_service_tracer


@asynccontextmanager
async def trace_service_boundary(
    service_name: str,
    operation_name: str,
    correlation_id: str,
    user_id: Optional[str] = None,
    parent_context: Optional[Dict[str, str]] = None,
    attributes: Optional[Dict[str, Any]] = None
) -> AsyncIterator[trace.Span]:
    tracer = get_service_tracer(service_name)
    
    async with tracer.start_distributed_span(
        operation_name,
        correlation_id,
        parent_context=parent_context,
        user_id=user_id,
        attributes=attributes
    ) as span:
        yield span


class TraceContextManager:
    def __init__(self):
        self._current_context: Optional[Dict[str, str]] = None
        self._correlation_id: Optional[str] = None
        self._user_id: Optional[str] = None
    
    def set_context(
        self,
        correlation_id: str,
        user_id: Optional[str] = None,
        trace_context: Optional[Dict[str, str]] = None
    ) -> None:
        self._correlation_id = correlation_id
        self._user_id = user_id
        self._current_context = trace_context or {}
    
    def get_context(self) -> Dict[str, str]:
        return self._current_context or {}
    
    def get_correlation_id(self) -> str:
        return self._correlation_id or str(uuid.uuid4())
    
    def get_user_id(self) -> str:
        return self._user_id or "system"
    
    def create_child_context(self, operation: str, service: str) -> Dict[str, str]:
        context = self._current_context.copy() if self._current_context else {}
        context.update({
            "x-correlation-id": self.get_correlation_id(),
            "x-user-id": self.get_user_id(),
            "x-operation": operation,
            "x-service": service,
            "x-parent-operation": context.get("x-operation", "root"),
            "x-parent-service": context.get("x-service", "unknown")
        })
        return context


_trace_context_manager = TraceContextManager()


def get_trace_context() -> TraceContextManager:
    return _trace_context_manager