# src/app/observability/app_insights.py
from __future__ import annotations

import os
from typing import Any

from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import metrics, trace
from opentelemetry.sdk.resources import Resource

from app.core.config import settings
from app.core.logging import get_logger
from app.observability.otel_patch import apply_all_patches

logger = get_logger(__name__)


class ApplicationInsights:
    _instance: ApplicationInsights | None = None
    _initialized: bool = False

    def __new__(cls) -> ApplicationInsights:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # Only initialize once at the class level
        if not ApplicationInsights._initialized:
            self.initialize()

    def initialize(self) -> None:
        if ApplicationInsights._initialized:
            logger.debug("Application Insights already initialized, skipping")
            return

        connection_string = (
            settings.observability.applicationinsights_connection_string
            or os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
        )

        if not connection_string:
            logger.warning("Application Insights connection string not configured")
            return

        service_name = settings.observability.otel_service_name or os.getenv(
            "OTEL_SERVICE_NAME", "devops-ai-api"
        )

        if settings.environment == "development":
            os.environ.setdefault("OTEL_BSP_SCHEDULE_DELAY", "15000")
            os.environ.setdefault("OTEL_BLRP_SCHEDULE_DELAY", "15000")

        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": settings.app_version,
                "deployment.environment": settings.environment,
                "cloud.provider": "azure",
                "cloud.platform": "azure_app_service",
            }
        )

        # Apply comprehensive OpenTelemetry patches to prevent attribute validation errors
        apply_all_patches()
        
        configure_azure_monitor(
            connection_string=connection_string,
            resource=resource,
            logger_name="app",
            instrumentation_options={
                "fastapi": {"enabled": True},
                "psycopg2": {"enabled": True},
                "django": {"enabled": False},
                "flask": {"enabled": False},
                "azure_sdk": {"enabled": True},
            },
        )

        self._setup_custom_metrics()

        ApplicationInsights._initialized = True
        logger.info(
            "Application Insights initialized",
            service_name=service_name,
            environment=settings.environment,
        )

    def _setup_custom_metrics(self) -> None:
        meter = metrics.get_meter(__name__)

        self.auth_counter = meter.create_counter(
            name="auth.attempts",
            description="Authentication attempts",
            unit="1",
        )

        self.auth_success_counter = meter.create_counter(
            name="auth.success",
            description="Successful authentications",
            unit="1",
        )

        self.auth_failure_counter = meter.create_counter(
            name="auth.failures",
            description="Failed authentications",
            unit="1",
        )

        self.token_validation_histogram = meter.create_histogram(
            name="token.validation.duration",
            description="Token validation duration",
            unit="ms",
        )

        self.deployment_counter = meter.create_counter(
            name="deployments.total",
            description="Total deployments",
            unit="1",
        )

        self.cost_analysis_counter = meter.create_counter(
            name="cost.analysis.requests",
            description="Cost analysis requests",
            unit="1",
        )

    def track_auth_attempt(self, method: str, success: bool, user_id: str | None = None) -> None:
        attributes = {
            "auth.method": method,
            "auth.success": str(success),
        }
        if user_id:
            attributes["user.id"] = user_id

        self.auth_counter.add(1, attributes)
        if success:
            self.auth_success_counter.add(1, attributes)
        else:
            self.auth_failure_counter.add(1, attributes)

    def track_token_validation(self, duration_ms: float, success: bool) -> None:
        self.token_validation_histogram.record(duration_ms, {"validation.success": str(success)})

    def track_deployment(self, environment: str, success: bool, resource_type: str) -> None:
        self.deployment_counter.add(
            1,
            {
                "deployment.environment": environment,
                "deployment.success": str(success),
                "resource.type": resource_type,
            },
        )

    def track_cost_analysis(self, subscription_id: str, time_range_days: int) -> None:
        self.cost_analysis_counter.add(
            1,
            {
                "subscription.id": subscription_id[:8],
                "time_range.days": str(time_range_days),
            },
        )

    def track_custom_event(self, name: str, properties: dict[str, Any] | None = None) -> None:
        span = trace.get_current_span()
        if span:
            span.add_event(name, attributes=properties or {})

    def track_exception(
        self, exception: Exception, properties: dict[str, Any] | None = None
    ) -> None:
        span = trace.get_current_span()
        if span:
            span.record_exception(exception, attributes=properties or {})
            
    def _patch_otel_attributes(self) -> None:
        """Patch OpenTelemetry attribute validation to handle logger objects."""
        try:
            from opentelemetry.util import attributes
            original_is_valid_attribute_value = attributes.is_valid_attribute_value
            
            def patched_is_valid_attribute_value(value: Any) -> bool:
                # Handle logger objects specifically
                if hasattr(value, '__class__') and 'Logger' in value.__class__.__name__:
                    return False  # Reject logger objects
                return original_is_valid_attribute_value(value)
            
            attributes.is_valid_attribute_value = patched_is_valid_attribute_value
            logger.debug("OpenTelemetry attribute validation patched successfully")
        except Exception as e:
            logger.warning(f"Failed to patch OpenTelemetry attributes: {e}")
            
    def _sanitize_attributes(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Sanitize attributes to prevent OpenTelemetry validation errors."""
        sanitized = {}
        for key, value in attrs.items():
            if key.startswith('_'):
                continue  # Skip private attributes
            if hasattr(value, '__class__') and 'Logger' in value.__class__.__name__:
                continue  # Skip logger objects
            sanitized[key] = value
        return sanitized


app_insights = ApplicationInsights()
