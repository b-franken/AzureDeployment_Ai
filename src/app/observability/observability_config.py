from __future__ import annotations

import os
from typing import Dict, List, Optional

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource

from app.core.config import settings
from app.core.logging import get_logger
from .app_insights import app_insights

logger = get_logger(__name__)


class ObservabilityConfig:
    def __init__(self):
        self._initialized = False
        self.service_name = settings.observability.otel_service_name or "devops-ai-api"
        self.service_version = getattr(settings, "version", "1.0.0")
        self.environment = settings.environment or "dev"
        
    def initialize_telemetry(self) -> None:
        if self._initialized:
            return
            
        try:
            resource = Resource.create({
                SERVICE_NAME: self.service_name,
                SERVICE_VERSION: self.service_version,
                "environment": self.environment,
                "service.namespace": "devops-ai",
                "service.instance.id": os.environ.get("HOSTNAME", "local"),
                "deployment.type": "containerized" if os.environ.get("CONTAINER_MODE") else "standalone"
            })
            
            tracer_provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(tracer_provider)
            
            if settings.observability.enable_otlp_export:
                otlp_exporter = OTLPSpanExporter(
                    endpoint=settings.observability.otel_exporter_otlp_endpoint,
                    headers={"authorization": f"Bearer {settings.observability.otel_exporter_otlp_headers}"}
                )
                span_processor = BatchSpanProcessor(
                    otlp_exporter,
                    max_queue_size=2048,
                    max_export_batch_size=512,
                    export_timeout_millis=30000
                )
                tracer_provider.add_span_processor(span_processor)
            
            self._instrument_libraries()
            self._initialize_service_boundaries()
            
            self._initialized = True
            
            logger.info(
                "Observability telemetry initialized",
                service_name=self.service_name,
                service_version=self.service_version,
                environment=self.environment,
                otlp_enabled=settings.observability.enable_otlp_export
            )
            
            app_insights.track_custom_event(
                "observability_initialized",
                {
                    "service_name": self.service_name,
                    "service_version": self.service_version,
                    "environment": self.environment,
                    "otlp_enabled": str(settings.observability.enable_otlp_export)
                }
            )
            
        except Exception as e:
            logger.error(
                "Failed to initialize observability telemetry", 
                error=str(e),
                exc_info=True
            )
            app_insights.track_exception(e)
    
    def _instrument_libraries(self) -> None:
        try:
            FastAPIInstrumentor.instrument()
            
            if settings.database.postgres_dsn:
                AsyncPGInstrumentor().instrument()
                logger.info("Instrumented AsyncPG for PostgreSQL tracing")
            
            if settings.database.redis_dsn:
                RedisInstrumentor().instrument()
                logger.info("Instrumented Redis for caching tracing")
            
            HTTPXClientInstrumentor().instrument()
            logger.info("Instrumented HTTPX for HTTP client tracing")
            
        except Exception as e:
            logger.warning(
                "Failed to instrument some libraries for tracing",
                error=str(e)
            )
    
    def _initialize_service_boundaries(self) -> None:
        from .distributed_tracing import ServiceRegistry
        
        service_boundaries = [
            "api_gateway",
            "intelligent_provision_service", 
            "provisioning_orchestrator",
            "nlu_service",
            "agent_memory_service",
            "azure_resource_manager",
            "cost_estimation_service",
            "deployment_validation_service"
        ]
        
        for service_name in service_boundaries:
            ServiceRegistry.register_service(service_name)
        
        logger.info(
            "Service boundaries initialized for distributed tracing",
            service_count=len(service_boundaries),
            services=service_boundaries
        )
    
    def get_service_info(self) -> Dict[str, str]:
        return {
            "service_name": self.service_name,
            "service_version": self.service_version,
            "environment": self.environment,
            "initialized": str(self._initialized)
        }
    
    def get_tracing_health(self) -> Dict[str, any]:
        from .distributed_tracing import ServiceRegistry
        
        return {
            "tracer_provider_active": trace.get_tracer_provider() is not None,
            "registered_services": len(ServiceRegistry._tracers),
            "service_names": list(ServiceRegistry._tracers.keys()),
            "app_insights_enabled": app_insights is not None,
            "otlp_export_enabled": settings.observability.enable_otlp_export
        }


_observability_config: Optional[ObservabilityConfig] = None


def get_observability_config() -> ObservabilityConfig:
    global _observability_config
    if _observability_config is None:
        _observability_config = ObservabilityConfig()
    return _observability_config


def initialize_observability() -> None:
    config = get_observability_config()
    config.initialize_telemetry()


def get_observability_health() -> Dict[str, any]:
    config = get_observability_config()
    return {
        "service_info": config.get_service_info(),
        "tracing_health": config.get_tracing_health()
    }