from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from app.core.logging import get_logger

logger = get_logger(__name__)


class AgentServiceMapper:
    _service_mappings: dict[str, str] = {
        "UnifiedAgent": "agent-unified",
        "OrchestrationAgent": "agent-orchestration", 
        "ProvisioningAgent": "agent-provisioning",
        "ReactiveAgent": "agent-reactive",
        "CoordinatorAgent": "agent-coordinator",
        "ChainAgent": "agent-chain",
        "ResourceIntelligence": "agent-resource-intelligence",
        "DependencyAnalyzer": "agent-dependency-analyzer",
        "LearningIntegrationService": "agent-learning-integration",
    }
    
    _resource_cache: dict[str, Resource] = {}

    @classmethod
    def get_service_name(cls, agent_class_name: str) -> str:
        return cls._service_mappings.get(
            agent_class_name, 
            f"agent-{agent_class_name.lower()}"
        )

    @classmethod
    def create_agent_resource(cls, agent_class_name: str) -> Resource:
        if agent_class_name in cls._resource_cache:
            return cls._resource_cache[agent_class_name]
            
        service_name = cls.get_service_name(agent_class_name)
        
        resource = Resource.create({
            "service.name": service_name,
            "service.version": os.getenv("APP_VERSION", "1.0.0"),
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
            "cloud.provider": "azure",
            "cloud.platform": "azure_app_service",
            "telemetry.sdk.name": "opentelemetry",
            "telemetry.sdk.language": "python",
            "service.namespace": "ai.agents",
            "agent.class": agent_class_name,
            "agent.type": "ai_agent",
        })
        
        cls._resource_cache[agent_class_name] = resource
        logger.debug(f"Created resource for agent: {agent_class_name} → {service_name}")
        return resource

    @classmethod
    @contextmanager
    def with_agent_context(
        cls, 
        agent_class_name: str,
        operation: str,
        attributes: dict[str, Any] | None = None
    ) -> Generator[trace.Span, None, None]:
        service_name = cls.get_service_name(agent_class_name)
        tracer = trace.get_tracer(service_name)
        
        span_attributes = {
            "agent.class": agent_class_name,
            "agent.operation": operation,
            "service.name": service_name,
        }
        
        if attributes:
            span_attributes.update(attributes)
            
        with tracer.start_as_current_span(
            f"{agent_class_name}.{operation}",
            attributes=span_attributes
        ) as span:
            yield span

    @classmethod
    def setup_agent_tracing_provider(cls, agent_class_name: str) -> TracerProvider:
        resource = cls.create_agent_resource(agent_class_name)
        provider = TracerProvider(resource=resource)
        
        logger.info(
            f"Set up tracing provider for agent: {agent_class_name}",
            service_name=cls.get_service_name(agent_class_name)
        )
        return provider

    @classmethod  
    def list_agent_services(cls) -> dict[str, str]:
        return cls._service_mappings.copy()

    @classmethod
    def register_agent_service(cls, agent_class_name: str, service_name: str) -> None:
        cls._service_mappings[agent_class_name] = service_name
        if agent_class_name in cls._resource_cache:
            del cls._resource_cache[agent_class_name]
        logger.info(f"Registered agent service: {agent_class_name} → {service_name}")


def get_agent_service_name(agent_class_name: str) -> str:
    return AgentServiceMapper.get_service_name(agent_class_name)