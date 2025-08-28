from __future__ import annotations
from app.observability.otel_patch import apply_all_patches
from app.core.logging import get_logger
from app.core.config import settings
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry import metrics, trace
from azure.monitor.opentelemetry import configure_azure_monitor

import logging
import os
from typing import Any


from app.observability.otel_fixes import ensure_proper_otel_initialization

ensure_proper_otel_initialization()


logger = get_logger(__name__)


class ApplicationInsights:
    _instance: ApplicationInsights | None = None
    _initialized: bool = False

    def __new__(cls) -> ApplicationInsights:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
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
            logger.warning(
                "Application Insights connection string not configured")
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
                "telemetry.sdk.name": "opentelemetry",
                "telemetry.sdk.language": "python",
                "service.namespace": "ai.agents",
            }
        )

        apply_all_patches()

        configure_azure_monitor(
            connection_string=connection_string,
            resource=resource,
            logger_name="app",
            instrumentation_options={
                "fastapi": {
                    "enabled": True,
                    "record_exception": True,
                    "capture_headers": True,
                },
                "psycopg2": {
                    "enabled": True,
                    "record_exception": True,
                    "capture_query": True,
                    "capture_parameters": False,
                },
                "asyncpg": {
                    "enabled": True,
                    "record_exception": True,
                    "capture_query": True,
                    "capture_parameters": False,
                },
                "postgresql": {
                    "enabled": True,
                    "record_exception": True,
                },
                "django": {"enabled": False},
                "flask": {"enabled": False},
                "azure_sdk": {
                    "enabled": True,
                    "record_exception": True,
                },
                "httpx": {
                    "enabled": True,
                    "record_exception": True,
                    "capture_request_headers": True,
                    "capture_response_headers": True,
                    "skip_dep_check": True,
                },
                "requests": {
                    "enabled": True,
                    "record_exception": True,
                    "capture_request_headers": True,
                    "capture_response_headers": True,
                },
                "urllib": {
                    "enabled": True,
                    "record_exception": True,
                },
                "urllib3": {
                    "enabled": True,
                    "record_exception": True,
                },
            },
        )

        self._setup_http_instrumentation()

        self._setup_database_instrumentation()

        self._setup_custom_metrics()
        self._configure_logger_levels()

        ApplicationInsights._initialized = True
        logger.info(
            "Application Insights initialized",
            service_name=service_name,
            environment=settings.environment,
            log_level=settings.log_level,
            debug_mode=settings.debug,
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
        self.token_validation_histogram.record(
            duration_ms, {"validation.success": str(success)})

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

    def track_custom_event(
        self,
        name: str,
        properties: dict[str, Any] | None = None,
        measurements: dict[str, float] | None = None,
    ) -> None:
        span = trace.get_current_span()
        if span:
            attributes = {}
            if properties:
                attributes.update(properties)
            if measurements:
                for key, value in measurements.items():
                    attributes[f"measurement.{key}"] = value
            span.add_event(name, attributes=attributes)

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
                if hasattr(value, "__class__") and "Logger" in value.__class__.__name__:
                    return False
                return original_is_valid_attribute_value(value)

            attributes.is_valid_attribute_value = patched_is_valid_attribute_value
            logger.debug(
                "OpenTelemetry attribute validation patched successfully")
        except (ImportError, AttributeError, TypeError) as e:
            logger.warning(f"Failed to patch OpenTelemetry attributes: {e}")

    def _sanitize_attributes(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Sanitize attributes to prevent OpenTelemetry validation errors."""
        sanitized = {}
        for key, value in attrs.items():
            if key.startswith("_"):
                continue
            if hasattr(value, "__class__") and "Logger" in value.__class__.__name__:
                continue
            sanitized[key] = value
        return sanitized

    def _setup_http_instrumentation(self) -> None:
        """Explicitly set up HTTP client instrumentation for comprehensive request tracking."""
        try:

            HTTPXClientInstrumentor().instrument(
                tracer_provider=trace.get_tracer_provider(),
                request_hook=self._http_request_hook,
                response_hook=self._http_response_hook,
            )

            RequestsInstrumentor().instrument(
                tracer_provider=trace.get_tracer_provider(),
                request_hook=self._http_request_hook,
                response_hook=self._http_response_hook,
            )

            logger.info("HTTP client instrumentation configured successfully")

        except (ImportError, RuntimeError, ValueError) as e:
            logger.warning(f"Failed to configure HTTP instrumentation: {e}")

    def _setup_database_instrumentation(self) -> None:
        """Set up database instrumentation for PostgreSQL visibility in Application Map."""
        try:

            try:
                from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

                AsyncPGInstrumentor().instrument(
                    tracer_provider=trace.get_tracer_provider(),
                    enable_commenter=True,
                    commenter_options={
                        "db_driver": True,
                        "dbapi_threadsafety": True,
                        "dbapi_level": True,
                        "libpq_version": True,
                        "driver_paramstyle": True,
                    },
                )
                logger.info(
                    "AsyncPG database instrumentation configured successfully")

            except ImportError:
                logger.debug("AsyncPG instrumentation not available, skipping")

            try:
                from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor

                Psycopg2Instrumentor().instrument(
                    tracer_provider=trace.get_tracer_provider(),
                    enable_commenter=True,
                )
                logger.info(
                    "Psycopg2 database instrumentation configured successfully")

            except ImportError:
                logger.debug(
                    "Psycopg2 instrumentation not available, skipping")

            logger.info("Database instrumentation setup completed")

        except (ImportError, RuntimeError, ValueError) as e:
            logger.warning(
                f"Failed to configure database instrumentation: {e}")

    def _http_request_hook(self, span: Any, request: Any) -> None:
        """Hook to enrich HTTP request spans with additional context."""
        try:
            if hasattr(request, "url"):
                url = str(request.url)

                if "api.openai.com" in url:
                    span.set_attribute("llm.vendor", "openai")
                    span.set_attribute("http.url.domain", "api.openai.com")

                    if hasattr(request, "content") and request.content:
                        try:
                            import json

                            body = json.loads(request.content.decode("utf-8"))
                            if isinstance(body, dict) and "model" in body:
                                span.set_attribute(
                                    "llm.request.model", body["model"])
                        except (ValueError, TypeError, KeyError, AttributeError):
                            pass

                span.set_attribute("http.request.method",
                                   getattr(request, "method", "unknown"))
                span.set_attribute("component", "http_client")

        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(f"HTTP request hook error: {e}")

    def _http_response_hook(self, span: Any, request: Any, response: Any) -> None:
        """Hook to enrich HTTP response spans with additional context."""
        try:
            if hasattr(response, "status_code"):
                span.set_attribute(
                    "http.response.status_code", response.status_code)

                if 200 <= response.status_code < 400:
                    span.set_attribute("http.response.success", True)
                else:
                    span.set_attribute("http.response.success", False)

            if hasattr(request, "url") and "api.openai.com" in str(request.url):
                if hasattr(response, "content"):
                    try:
                        import json

                        response_data = json.loads(
                            response.content.decode("utf-8"))
                        if isinstance(response_data, dict) and "usage" in response_data:
                            usage = response_data["usage"]
                            if isinstance(usage, dict):
                                for key, value in usage.items():
                                    if isinstance(value, int | float):
                                        span.set_attribute(
                                            f"llm.usage.{key}", value)
                    except (ValueError, TypeError, KeyError, AttributeError):
                        pass

        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(f"HTTP response hook error: {e}")

    def _configure_logger_levels(self) -> None:
        """Configure third-party logger levels based on application settings."""

        configured_level = getattr(
            logging, settings.log_level.upper(), logging.INFO)

        if settings.debug:

            azure_level = logging.INFO
        else:

            azure_level = max(configured_level, logging.WARNING)

        logger.debug(
            "Configuring third-party logger levels",
            configured_level=settings.log_level,
            debug_mode=settings.debug,
            azure_level=logging.getLevelName(azure_level),
        )

        logging.getLogger(
            "azure.core.pipeline.policies.http_logging_policy").setLevel(azure_level)
        logging.getLogger("azure.monitor.opentelemetry").setLevel(azure_level)
        logging.getLogger("azure.core").setLevel(azure_level)
        logging.getLogger("azure.identity").setLevel(azure_level)
        logging.getLogger("azure.mgmt").setLevel(azure_level)

        if settings.debug:
            logging.getLogger("httpx").setLevel(logging.DEBUG)
            logging.getLogger("urllib3").setLevel(logging.INFO)
            logging.getLogger("requests").setLevel(logging.DEBUG)
        else:

            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            logging.getLogger("requests").setLevel(logging.WARNING)

        if settings.debug:
            logging.getLogger("opentelemetry").setLevel(logging.INFO)
        else:
            logging.getLogger("opentelemetry").setLevel(logging.WARNING)


app_insights = ApplicationInsights()
