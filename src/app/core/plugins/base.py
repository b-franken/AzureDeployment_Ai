from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, UTC
from enum import Enum

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

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
    dependencies: List[str] = None
    configuration_schema: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []
        if self.configuration_schema is None:
            self.configuration_schema = {}


class PluginConfig(BaseSchema):
    enabled: bool = True
    configuration: Dict[str, Any] = Field(default_factory=dict)
    load_priority: int = Field(default=0, description="Lower numbers load first")
    auto_reload: bool = Field(default=False, description="Enable hot reload in development")


class PluginContext(BaseSchema):
    plugin_name: str
    execution_context: Dict[str, Any] = Field(default_factory=dict)
    request_metadata: Dict[str, Any] = Field(default_factory=dict)
    user_context: Dict[str, Any] = Field(default_factory=dict)


class PluginResult(BaseSchema):
    success: bool
    result: Any = None
    error_message: str | None = None
    warnings: List[str] = Field(default_factory=list)
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Plugin(ABC):
    def __init__(self, metadata: PluginMetadata, config: PluginConfig):
        self.metadata = metadata
        self.config = config
        self.status = PluginStatus.INACTIVE
        self._initialized = False
        self._last_error: Optional[Exception] = None
    
    @abstractmethod
    async def initialize(self) -> None:
        pass
    
    @abstractmethod
    async def execute(self, context: PluginContext) -> PluginResult:
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        pass
    
    async def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        with tracer.start_as_current_span("plugin_validate_config") as span:
            span.set_attributes({
                "plugin.name": self.metadata.name,
                "plugin.type": self.metadata.plugin_type.value,
                "config.keys": list(config.keys())
            })
            
            errors = []
            
            if self.metadata.configuration_schema:
                try:
                    from jsonschema import validate, ValidationError
                    validate(instance=config, schema=self.metadata.configuration_schema)
                except ImportError:
                    errors.append("jsonschema library required for configuration validation")
                except ValidationError as e:
                    errors.append(f"Configuration validation error: {e.message}")
                except Exception as e:
                    errors.append(f"Configuration validation failed: {str(e)}")
            
            span.set_attributes({
                "validation.errors": len(errors),
                "validation.success": len(errors) == 0
            })
            
            if errors:
                span.set_status(Status(StatusCode.ERROR, f"Configuration validation failed with {len(errors)} errors"))
            else:
                span.set_status(Status(StatusCode.OK))
            
            return errors
    
    async def health_check(self) -> Dict[str, Any]:
        with tracer.start_as_current_span("plugin_health_check") as span:
            span.set_attributes({
                "plugin.name": self.metadata.name,
                "plugin.status": self.status.value,
                "plugin.initialized": self._initialized
            })
            
            health_status = {
                "name": self.metadata.name,
                "status": self.status.value,
                "initialized": self._initialized,
                "last_error": str(self._last_error) if self._last_error else None,
                "timestamp": datetime.now(UTC).isoformat(),
                "metadata": {
                    "version": self.metadata.version,
                    "type": self.metadata.plugin_type.value,
                    "author": self.metadata.author
                }
            }
            
            span.set_attributes({
                "health.status": self.status.value,
                "health.has_error": self._last_error is not None
            })
            span.set_status(Status(StatusCode.OK))
            
            return health_status
    
    def set_status(self, status: PluginStatus, error: Optional[Exception] = None) -> None:
        with tracer.start_as_current_span("plugin_set_status") as span:
            old_status = self.status
            self.status = status
            
            if error:
                self._last_error = error
            elif status == PluginStatus.ACTIVE:
                self._last_error = None
            
            span.set_attributes({
                "plugin.name": self.metadata.name,
                "status.old": old_status.value,
                "status.new": status.value,
                "status.has_error": error is not None
            })
            
            if error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, str(error)))
            else:
                span.set_status(Status(StatusCode.OK))
    
    def get_plugin_info(self) -> Dict[str, Any]:
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
            "auto_reload": self.config.auto_reload
        }
    
    def __str__(self) -> str:
        return f"{self.metadata.name} v{self.metadata.version} ({self.status.value})"
    
    def __repr__(self) -> str:
        return f"Plugin(name='{self.metadata.name}', version='{self.metadata.version}', status='{self.status.value}')"