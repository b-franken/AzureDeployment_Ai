from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import Field

from app.core.schemas.base import BaseSchema

tracer = trace.get_tracer(__name__)


class PluginStatus(str, Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


class PluginType(str, Enum):
    RESOURCE_TEMPLATE = "resource_template"
    FUNCTION_EXTENSION = "function_extension"
    MIDDLEWARE = "middleware"
    PROVIDER = "provider"
    CUSTOM = "custom"


@dataclass
class PluginMetadata:
    name: str
    version: str
    description: str
    author: str
    plugin_type: PluginType
    dependencies: list[str] | None = None
    configuration_schema: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.dependencies is None:
            self.dependencies = []
        if self.configuration_schema is None:
            self.configuration_schema = {}


class PluginConfig(BaseSchema):
    enabled: bool = True
    configuration: dict[str, Any] = Field(default_factory=dict)
    load_priority: int = Field(default=0, description="Lower numbers load first")
    auto_reload: bool = Field(default=False, description="Enable hot reload in development")


class PluginContext(BaseSchema):
    plugin_name: str
    execution_context: dict[str, Any] = Field(default_factory=dict)
    request_metadata: dict[str, Any] = Field(default_factory=dict)
    user_context: dict[str, Any] = Field(default_factory=dict)


class PluginResult(BaseSchema):
    success: bool
    result: Any = None
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    execution_time_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class Plugin(ABC):
    def __init__(self, metadata: PluginMetadata, config: PluginConfig):
        self.metadata = metadata
        self.config = config
        self.status = PluginStatus.INACTIVE
        self._initialized = False
        self._last_error: Exception | None = None

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the plugin. Subclasses should implement their initialization logic."""
        pass

    @abstractmethod
    async def execute(self, context: PluginContext) -> PluginResult:
        """Execute the plugin with given context. Subclasses must implement this."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Shutdown the plugin. Subclasses should implement cleanup logic."""
        pass

    async def safe_initialize(self) -> None:
        """Safe wrapper for plugin initialization with comprehensive logging."""
        from app.core.logging import get_logger

        logger = get_logger(__name__)

        with tracer.start_as_current_span("plugin_safe_initialize") as span:
            span.set_attributes(
                {
                    "plugin.name": self.metadata.name,
                    "plugin.type": self.metadata.plugin_type.value,
                    "plugin.version": self.metadata.version,
                }
            )

            try:
                logger.debug(
                    "plugin_initialize_started",
                    plugin_name=self.metadata.name,
                    plugin_type=self.metadata.plugin_type.value,
                    plugin_version=self.metadata.version,
                )

                await self.initialize()

                self._initialized = True
                self.set_status(PluginStatus.ACTIVE)

                span.set_attributes({"initialization.success": True, "plugin.initialized": True})

                logger.info(
                    "plugin_initialize_completed",
                    plugin_name=self.metadata.name,
                    initialized=True,
                    status=self.status.value,
                )

            except Exception as e:
                self._initialized = False
                self.set_status(PluginStatus.ERROR, e)

                span.record_exception(e)
                span.set_attributes(
                    {"initialization.success": False, "initialization.error": str(e)}
                )

                logger.error(
                    "plugin_initialize_failed",
                    plugin_name=self.metadata.name,
                    error=str(e),
                    error_type=type(e).__name__,
                    plugin_status=self.status.value,
                )
                raise

    async def safe_shutdown(self) -> None:
        """Safe wrapper for plugin shutdown with comprehensive logging."""
        from app.core.logging import get_logger

        logger = get_logger(__name__)

        with tracer.start_as_current_span("plugin_safe_shutdown") as span:
            span.set_attributes(
                {
                    "plugin.name": self.metadata.name,
                    "plugin.type": self.metadata.plugin_type.value,
                    "plugin.current_status": self.status.value,
                }
            )

            try:
                logger.debug(
                    "plugin_shutdown_started",
                    plugin_name=self.metadata.name,
                    current_status=self.status.value,
                    initialized=self._initialized,
                )

                await self.shutdown()

                self._initialized = False
                self.set_status(PluginStatus.INACTIVE)

                span.set_attributes({"shutdown.success": True, "plugin.initialized": False})

                logger.info(
                    "plugin_shutdown_completed",
                    plugin_name=self.metadata.name,
                    shutdown_successful=True,
                    status=self.status.value,
                )

            except Exception as e:
                self.set_status(PluginStatus.ERROR, e)

                span.record_exception(e)
                span.set_attributes({"shutdown.success": False, "shutdown.error": str(e)})

                logger.error(
                    "plugin_shutdown_failed",
                    plugin_name=self.metadata.name,
                    error=str(e),
                    error_type=type(e).__name__,
                    plugin_status=self.status.value,
                )
                raise

    async def validate_configuration(self, config: dict[str, Any]) -> list[str]:
        from app.core.logging import get_logger

        logger = get_logger(__name__)

        with tracer.start_as_current_span("plugin_validate_config") as span:
            span.set_attributes(
                {
                    "plugin.name": self.metadata.name,
                    "plugin.type": self.metadata.plugin_type.value,
                    "config.keys": list(config.keys()),
                    "config.size": len(config),
                    "has_schema": self.metadata.configuration_schema is not None,
                }
            )

            logger.debug(
                "plugin_config_validation_started",
                plugin_name=self.metadata.name,
                plugin_type=self.metadata.plugin_type.value,
                config_keys=list(config.keys()),
                has_schema=self.metadata.configuration_schema is not None,
            )

            errors: list[str] = []

            if self.metadata.configuration_schema:
                # Try to import jsonschema dependencies first
                try:
                    from jsonschema import ValidationError, validate
                except ImportError as import_err:
                    error_msg = "jsonschema library required for configuration validation"
                    errors.append(error_msg)

                    logger.warning(
                        "plugin_config_validation_import_failed",
                        plugin_name=self.metadata.name,
                        error=str(import_err),
                        required_library="jsonschema",
                        fallback_skip_validation=True,
                    )

                    span.record_exception(import_err)
                else:
                    # ValidationError is now guaranteed to be bound
                    try:
                        schema_keys = (
                            list(self.metadata.configuration_schema.keys())
                            if isinstance(self.metadata.configuration_schema, dict)
                            else []
                        )

                        logger.debug(
                            "plugin_config_jsonschema_validation",
                            plugin_name=self.metadata.name,
                            schema_keys=schema_keys,
                            jsonschema_available=True,
                        )

                        validate(instance=config, schema=self.metadata.configuration_schema)

                        logger.debug(
                            "plugin_config_validation_passed",
                            plugin_name=self.metadata.name,
                            config_valid=True,
                        )

                    except ValidationError as validation_err:
                        error_msg = f"Configuration validation error: {validation_err.message}"
                        errors.append(error_msg)

                        validation_path = list(validation_err.path) if validation_err.path else []
                        schema_path = (
                            list(validation_err.schema_path) if validation_err.schema_path else []
                        )
                        invalid_value = (
                            str(validation_err.instance)[:200]
                            if hasattr(validation_err, "instance")
                            else None
                        )

                        logger.error(
                            "plugin_config_validation_failed",
                            plugin_name=self.metadata.name,
                            validation_error=validation_err.message,
                            validation_path=validation_path,
                            schema_path=schema_path,
                            invalid_value=invalid_value,
                        )

                        span.record_exception(validation_err)

                    except Exception as e:
                        error_msg = f"Configuration validation failed: {str(e)}"
                        errors.append(error_msg)

                        logger.error(
                            "plugin_config_validation_unexpected_error",
                            plugin_name=self.metadata.name,
                            error=str(e),
                            error_type=type(e).__name__,
                            config_preview=str(config)[:200] if config else "empty",
                        )

                        span.record_exception(e)
            else:
                logger.debug(
                    "plugin_config_validation_skipped",
                    plugin_name=self.metadata.name,
                    reason="no_configuration_schema",
                )

            span.set_attributes(
                {
                    "validation.errors": len(errors),
                    "validation.success": len(errors) == 0,
                    "validation.error_messages": (
                        errors[:5] if errors else []
                    ),  # Limit for telemetry
                }
            )

            if errors:
                span.set_status(
                    Status(
                        StatusCode.ERROR,
                        f"Configuration validation failed with {len(errors)} errors",
                    )
                )

                logger.error(
                    "plugin_config_validation_completed_with_errors",
                    plugin_name=self.metadata.name,
                    error_count=len(errors),
                    errors=errors,
                )
            else:
                span.set_status(Status(StatusCode.OK))

                logger.info(
                    "plugin_config_validation_completed_successfully",
                    plugin_name=self.metadata.name,
                    config_valid=True,
                )

            return errors

    async def health_check(self) -> dict[str, Any]:
        from app.core.logging import get_logger

        logger = get_logger(__name__)

        with tracer.start_as_current_span("plugin_health_check") as span:
            try:
                span.set_attributes(
                    {
                        "plugin.name": self.metadata.name,
                        "plugin.status": self.status.value,
                        "plugin.initialized": self._initialized,
                        "plugin.type": self.metadata.plugin_type.value,
                        "plugin.version": self.metadata.version,
                    }
                )

                logger.debug(
                    "plugin_health_check_started",
                    plugin_name=self.metadata.name,
                    current_status=self.status.value,
                    initialized=self._initialized,
                    has_error=self._last_error is not None,
                )

                health_status = {
                    "name": self.metadata.name,
                    "status": self.status.value,
                    "initialized": self._initialized,
                    "last_error": str(self._last_error) if self._last_error else None,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "metadata": {
                        "version": self.metadata.version,
                        "type": self.metadata.plugin_type.value,
                        "author": self.metadata.author,
                        "dependencies": self.metadata.dependencies or [],
                    },
                    "config": {
                        "enabled": self.config.enabled,
                        "load_priority": self.config.load_priority,
                        "auto_reload": self.config.auto_reload,
                    },
                }

                span.set_attributes(
                    {
                        "health.status": self.status.value,
                        "health.has_error": self._last_error is not None,
                        "health.enabled": self.config.enabled,
                        "health.dependencies_count": len(self.metadata.dependencies or []),
                    }
                )
                span.set_status(Status(StatusCode.OK))

                logger.debug(
                    "plugin_health_check_completed",
                    plugin_name=self.metadata.name,
                    health_status=self.status.value,
                    health_check_successful=True,
                )

                return health_status

            except Exception as e:
                logger.error(
                    "plugin_health_check_failed",
                    plugin_name=self.metadata.name,
                    error=str(e),
                    error_type=type(e).__name__,
                )

                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))

                # Return minimal health status on error
                return {
                    "name": self.metadata.name,
                    "status": "error",
                    "initialized": False,
                    "last_error": f"Health check failed: {str(e)}",
                    "timestamp": datetime.now(UTC).isoformat(),
                }

    def set_status(self, status: PluginStatus, error: Exception | None = None) -> None:
        from app.core.logging import get_logger

        logger = get_logger(__name__)

        with tracer.start_as_current_span("plugin_set_status") as span:
            try:
                old_status = self.status
                self.status = status

                if error:
                    self._last_error = error
                elif status == PluginStatus.ACTIVE:
                    self._last_error = None

                span.set_attributes(
                    {
                        "plugin.name": self.metadata.name,
                        "status.old": old_status.value,
                        "status.new": status.value,
                        "status.has_error": error is not None,
                        "plugin.type": self.metadata.plugin_type.value,
                    }
                )

                logger.info(
                    "plugin_status_changed",
                    plugin_name=self.metadata.name,
                    old_status=old_status.value,
                    new_status=status.value,
                    has_error=error is not None,
                    error_message=str(error) if error else None,
                    error_type=type(error).__name__ if error else None,
                )

                if error:
                    span.record_exception(error)
                    span.set_status(Status(StatusCode.ERROR, str(error)))

                    logger.error(
                        "plugin_status_set_with_error",
                        plugin_name=self.metadata.name,
                        new_status=status.value,
                        error=str(error),
                        error_type=type(error).__name__,
                    )
                else:
                    span.set_status(Status(StatusCode.OK))

                    logger.debug(
                        "plugin_status_set_successfully",
                        plugin_name=self.metadata.name,
                        new_status=status.value,
                        status_change_successful=True,
                    )

            except Exception as e:
                logger.error(
                    "plugin_set_status_failed",
                    plugin_name=self.metadata.name,
                    intended_status=status.value if status else "unknown",
                    error=str(e),
                    error_type=type(e).__name__,
                )

                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, f"Failed to set status: {str(e)}"))
                raise

    def get_plugin_info(self) -> dict[str, Any]:
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "description": self.metadata.description,
            "author": self.metadata.author,
            "type": self.metadata.plugin_type.value,
            "status": self.status.value,
            "initialized": self._initialized,
            "dependencies": self.metadata.dependencies,
            "config_enabled": self.config.enabled,
            "load_priority": self.config.load_priority,
            "auto_reload": self.config.auto_reload,
        }

    def __str__(self) -> str:
        return f"{self.metadata.name} v{self.metadata.version} ({self.status.value})"

    def __repr__(self) -> str:
        return (
            f"Plugin(name='{self.metadata.name}', "
            f"version='{self.metadata.version}', status='{self.status.value}')"
        )
