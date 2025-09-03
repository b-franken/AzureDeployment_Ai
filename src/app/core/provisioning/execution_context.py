from __future__ import annotations

from enum import Enum
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import Field

from app.core.schemas.base import BaseSchema, TimestampedSchema
from app.core.schemas.mixins import AzureMixin
from app.core.schemas.registry import register_schema

tracer = trace.get_tracer(__name__)


class ProvisioningPhase(str, Enum):
    VALIDATION = "validation"
    PARSING = "parsing"
    PLANNING = "planning"
    EXECUTION = "execution"
    FALLBACK = "fallback"
    COMPLETION = "completion"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@register_schema(version="1.0.0", category="provisioning")
class ProvisionContext(TimestampedSchema, AzureMixin):
    request_text: str = Field(description="Original natural language request")
    user_id: str = Field(description="User identifier")
    dry_run: bool = Field(default=True, description="Execute in dry-run mode")
    environment: str = Field(default="dev", description="Target environment")  # type: ignore[assignment]
    name_prefix: str = Field(default="app", description="Resource naming prefix")

    parsed_resources: list[dict[str, Any]] = Field(
        default_factory=list, description="Parsed resource requirements"
    )
    deployment_plan: dict[str, Any] = Field(
        default_factory=dict, description="Generated deployment plan"
    )
    execution_metadata: dict[str, Any] = Field(
        default_factory=dict, description="Execution metadata"
    )

    current_phase: ProvisioningPhase = Field(
        default=ProvisioningPhase.VALIDATION, description="Current execution phase"
    )
    attempted_strategies: list[str] = Field(
        default_factory=list, description="List of attempted provisioning strategies"
    )

    enable_monitoring: bool = Field(default=True, description="Enable monitoring integration")
    cost_optimization: bool = Field(default=True, description="Apply cost optimizations")

    conversation_context: list[dict[str, str]] = Field(
        default_factory=list, description="Conversation history"
    )

    def advance_phase(self, new_phase: ProvisioningPhase | str) -> None:
        with tracer.start_as_current_span("context_advance_phase") as span:
            old_phase = self.current_phase

            if isinstance(new_phase, str):
                try:
                    self.current_phase = ProvisioningPhase(new_phase)
                except ValueError:
                    self.current_phase = ProvisioningPhase.VALIDATION
            else:
                self.current_phase = new_phase
            self.update_timestamp()

            old_phase_value = (
                old_phase.value if isinstance(old_phase, ProvisioningPhase) else str(old_phase)
            )
            new_phase_value = (
                new_phase.value if isinstance(new_phase, ProvisioningPhase) else str(new_phase)
            )

            span.set_attributes(
                {
                    "context.user_id": self.user_id,
                    "context.correlation_id": self.correlation_id,
                    "phase.old": old_phase_value,
                    "phase.new": new_phase_value,
                    "context.dry_run": self.dry_run,
                }
            )
            span.set_status(Status(StatusCode.OK))

    def add_attempted_strategy(self, strategy_name: str) -> None:
        with tracer.start_as_current_span("context_add_strategy") as span:
            if strategy_name not in self.attempted_strategies:
                self.attempted_strategies.append(strategy_name)

            span.set_attributes(
                {
                    "context.user_id": self.user_id,
                    "context.correlation_id": self.correlation_id,
                    "strategy.name": strategy_name,
                    "strategy.total_attempted": len(self.attempted_strategies),
                }
            )
            span.set_status(Status(StatusCode.OK))

    def get_execution_summary(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "current_phase": (
                self.current_phase.value
                if hasattr(self.current_phase, "value")
                else str(self.current_phase)
            ),
            "attempted_strategies": self.attempted_strategies,
            "resource_count": len(self.parsed_resources),
            "has_deployment_plan": bool(self.deployment_plan),
            "dry_run": self.dry_run,
            "environment": self.environment,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@register_schema(version="1.0.0", category="provisioning")
class ExecutionResult(BaseSchema):
    success: bool = Field(description="Whether execution was successful")
    strategy_used: str = Field(description="Strategy that produced this result")
    result_data: Any = None
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)

    execution_time_ms: float = Field(default=0.0, description="Execution time in milliseconds")
    resources_affected: list[str] = Field(
        default_factory=list, description="Resources that were created/modified"
    )

    observability_data: dict[str, Any] = Field(
        default_factory=dict, description="Telemetry and metrics data"
    )

    @classmethod
    def success_result(
        cls,
        strategy: str,
        data: Any,
        execution_time: float = 0.0,
        resources: list[str] | None = None,
        warnings: list[str] | None = None,
        output: Any = None,
    ) -> ExecutionResult:
        with tracer.start_as_current_span("execution_result_success") as span:
            # Add logging to track strategy setting
            from app.core.logging import get_logger
            logger = get_logger(__name__)
            logger.info(
                "Creating ExecutionResult.success_result",
                strategy_used=strategy,
                execution_time_ms=execution_time,
                resources_count=len(resources or []),
                has_data=data is not None,
                data_type=type(data).__name__ if data is not None else None,
            )
            
            result = cls(
                success=True,
                strategy_used=strategy,
                result_data=data,
                execution_time_ms=execution_time,
                resources_affected=resources or [],
                warnings=warnings or [],
            )

            span.set_attributes(
                {
                    "result.success": True,
                    "result.strategy": strategy,
                    "result.execution_time_ms": execution_time,
                    "result.resources_count": len(resources or []),
                    "result.warnings_count": len(warnings or []),
                }
            )
            span.set_status(Status(StatusCode.OK))

            return result

    @classmethod
    def failure_result(
        cls,
        strategy: str,
        error: str,
        execution_time: float = 0.0,
        warnings: list[str] | None = None,
    ) -> ExecutionResult:
        with tracer.start_as_current_span("execution_result_failure") as span:
            result = cls(
                success=False,
                strategy_used=strategy,
                error_message=error,
                execution_time_ms=execution_time,
                warnings=warnings or [],
            )

            span.set_attributes(
                {
                    "result.success": False,
                    "result.strategy": strategy,
                    "result.error": error,
                    "result.execution_time_ms": execution_time,
                    "result.warnings_count": len(warnings or []),
                }
            )
            span.set_status(Status(StatusCode.ERROR, error))

            return result

    def to_tool_result(self) -> dict[str, Any]:
        # Add logging to track final tool result formatting
        from app.core.logging import get_logger
        logger = get_logger(__name__)
        logger.info(
            "Converting ExecutionResult to tool result",
            success=self.success,
            strategy_used=self.strategy_used,
            execution_time_ms=self.execution_time_ms,
            resources_count=len(self.resources_affected),
            is_preview=(self.strategy_used == "preview_generation"),
        )
        
        if (
            self.success
            and self.strategy_used == "preview_generation"
            and isinstance(self.result_data, dict)
        ):
            preview_response = self.result_data.get("preview_response", "")
            return {
                "ok": True,
                "summary": "Deployment preview generated",
                "output": preview_response,
                "strategy": self.strategy_used,
                "execution_time_ms": self.execution_time_ms,
                "warnings": self.warnings,
                "correlation_id": getattr(self, "correlation_id", None),
            }

        return {
            "ok": self.success,
            "summary": (
                f"Strategy '{self.strategy_used}' {'succeeded' if self.success else 'failed'}"
            ),
            "output": self.result_data if self.success else self.error_message,
            "strategy": self.strategy_used,
            "execution_time_ms": self.execution_time_ms,
            "resources_affected": self.resources_affected,
            "warnings": self.warnings,
            "correlation_id": getattr(self, "correlation_id", None),
        }
