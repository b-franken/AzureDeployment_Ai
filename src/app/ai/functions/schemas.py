from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

import structlog
from pydantic import Field, ValidationInfo, field_validator

from app.core.schemas.base import BaseSchema, TimestampedSchema
from app.core.schemas.mixins import AzureMixin, ValidationMixin
from app.core.schemas.registry import register_schema

logger = structlog.get_logger(__name__)


class FunctionCallType(str, Enum):
    RESOURCE_ANALYSIS = "analyze_resource_requirements"
    DEPLOYMENT_PLANNING = "create_deployment_plan"
    COST_ESTIMATION = "estimate_deployment_cost"
    DEPENDENCY_ANALYSIS = "analyze_resource_dependencies"
    VALIDATION_CHECK = "validate_deployment_config"
    RESOURCE_RECOMMENDATION = "recommend_resources"


@register_schema(version="1.0.0", category="azure_functions")
class ResourceRequirements(BaseSchema, AzureMixin, ValidationMixin):
    resource_type: str = Field(description="Type of Azure resource")
    resource_name: str = Field(description="Name of the resource")
    sku: str | None = Field(default=None, description="Resource SKU/tier")
    configuration: dict[str, Any] = Field(
        default_factory=dict, description="Additional configuration parameters"
    )


@register_schema(version="1.0.0", category="azure_functions")
class DeploymentPlan(BaseSchema):
    resources: list[ResourceRequirements] = Field(description="Resources to deploy")
    deployment_order: list[str] = Field(description="Ordered list of resource names for deployment")
    parallel_groups: list[list[str]] = Field(
        default_factory=list, description="Groups of resources that can be deployed in parallel"
    )
    estimated_time_minutes: int = Field(description="Estimated deployment time in minutes")
    prerequisites: list[str] = Field(
        default_factory=list, description="Prerequisites that must exist"
    )
    warnings: list[str] = Field(default_factory=list, description="Deployment warnings")


@register_schema(version="1.0.0", category="azure_functions")
class CostEstimate(BaseSchema, AzureMixin):
    resource_name: str = Field(description="Name of the resource")
    resource_type: str = Field(description="Type of Azure resource")
    monthly_cost_usd: float = Field(description="Estimated monthly cost in USD")
    cost_factors: dict[str, Any] = Field(default_factory=dict, description="Factors affecting cost")
    tier: str = Field(description="Service tier")
    region: str = Field(description="Azure region")


@register_schema(version="1.0.0", category="azure_functions")
class DeploymentCostAnalysis(BaseSchema):
    total_monthly_cost_usd: float = Field(description="Total estimated monthly cost")
    resources: list[CostEstimate] = Field(description="Per-resource cost breakdown")
    cost_optimization_suggestions: list[str] = Field(
        default_factory=list, description="Cost optimization recommendations"
    )
    budget_alerts: list[str] = Field(default_factory=list, description="Budget warning messages")


@register_schema(version="1.0.0", category="azure_functions")
class ResourceDependency(BaseSchema):
    resource_name: str = Field(description="Resource name")
    depends_on: list[str] = Field(description="List of resources this depends on")
    deployment_group: int = Field(description="Deployment group number")
    estimated_deploy_time_minutes: int = Field(description="Estimated deployment time")


@register_schema(version="1.0.0", category="azure_functions")
class DependencyAnalysis(BaseSchema):
    dependencies: list[ResourceDependency] = Field(description="Resource dependencies")
    deployment_groups: list[list[str]] = Field(description="Ordered deployment groups")
    critical_path: list[str] = Field(description="Critical path resources")
    parallel_opportunities: int = Field(description="Number of parallel deployment opportunities")
    warnings: list[str] = Field(default_factory=list, description="Dependency warnings")


@register_schema(version="1.0.0", category="azure_functions")
class ValidationIssue(BaseSchema):
    level: Literal["error", "warning", "info"] = Field(description="Issue severity")
    resource: str = Field(description="Affected resource")
    message: str = Field(description="Issue description")
    suggestion: str | None = Field(default=None, description="Suggested fix")


@register_schema(version="1.0.0", category="azure_functions")
class ValidationResult(BaseSchema, ValidationMixin):
    is_valid: bool = Field(description="Whether configuration is valid")
    issues: list[ValidationIssue] = Field(description="Validation issues found")
    compliance_checks: dict[str, bool] = Field(
        default_factory=dict, description="Security and compliance validation"
    )
    best_practices: list[str] = Field(
        default_factory=list, description="Best practice recommendations"
    )


@register_schema(version="1.0.0", category="azure_functions")
class ResourceRecommendation(BaseSchema, AzureMixin):
    resource_type: str = Field(description="Recommended resource type")
    resource_name: str = Field(description="Suggested resource name")
    rationale: str = Field(description="Why this resource is recommended")
    priority: Literal["high", "medium", "low"] = Field(description="Recommendation priority")
    estimated_cost_impact: str = Field(description="Cost impact estimate")
    configuration: dict[str, Any] = Field(
        default_factory=dict, description="Recommended configuration"
    )


@register_schema(version="1.0.0", category="azure_functions")
class ResourceRecommendations(BaseSchema):
    primary_resource: str = Field(description="Primary resource being analyzed")
    recommendations: list[ResourceRecommendation] = Field(
        description="List of recommended resources"
    )
    architecture_patterns: list[str] = Field(
        default_factory=list, description="Suggested architecture patterns"
    )
    security_enhancements: list[str] = Field(
        default_factory=list, description="Security recommendations"
    )


@register_schema(version="1.0.0", category="azure_functions")
class FunctionCallRequest(TimestampedSchema):
    function: FunctionCallType = Field(description="Function to call")
    arguments: dict[str, Any] = Field(description="Function arguments")
    request_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), 
        description="Request initiation timestamp"
    )
    
    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v, dict):
            logger.error(
                "function_call_request_validation_error",
                error="arguments must be a dictionary",
                provided_type=type(v).__name__,
            )
            raise ValueError("arguments must be a dictionary")
        
        if len(v) == 0:
            logger.warning(
                "function_call_request_validation_warning",
                warning="arguments dictionary is empty",
            )
        
        logger.debug(
            "function_call_request_validation_success",
            arguments_count=len(v),
            argument_keys=list(v.keys()),
        )
        return v
    
    def log_function_call_start(self) -> None:
        logger.info(
            "function_call_started",
            function=self.function,
            correlation_id=self.correlation_id,
            arguments_count=len(self.arguments),
            timestamp=self.request_timestamp.isoformat(),
        )


@register_schema(version="1.0.0", category="azure_functions")
class FunctionCallResponse(TimestampedSchema):
    function: FunctionCallType = Field(description="Function that was called")
    success: bool = Field(description="Whether function call succeeded")
    result: Any = Field(description="Function result data")
    error: str | None = Field(default=None, description="Error message if failed")
    execution_time_ms: float = Field(description="Execution time in milliseconds")
    response_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), 
        description="Response completion timestamp"
    )
    
    @field_validator("execution_time_ms")
    @classmethod
    def validate_execution_time(cls, v: float) -> float:
        if v < 0:
            logger.error(
                "function_call_response_validation_error",
                error="execution_time_ms cannot be negative",
                provided_value=v,
            )
            raise ValueError("execution_time_ms cannot be negative")
        
        if v > 300_000:  # 5 minutes in milliseconds
            logger.warning(
                "function_call_response_validation_warning",
                warning="execution time exceeds 5 minutes",
                execution_time_ms=v,
            )
        
        return v
    
    @field_validator("error")
    @classmethod
    def validate_error_consistency(cls, v: str | None, info: ValidationInfo) -> str | None:
        success = info.data.get("success", True)
        
        if not success and not v:
            logger.error(
                "function_call_response_validation_error",
                error="error message is required when success=False",
            )
            raise ValueError("error message is required when success=False")
        
        if success and v:
            logger.warning(
                "function_call_response_validation_warning",
                warning="error message provided despite success=True",
                error_message=v,
            )
        
        return v
    
    def log_function_call_completion(self) -> None:
        log_data = {
            "function_call_completed": True,
            "function": self.function,
            "correlation_id": self.correlation_id,
            "success": self.success,
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.response_timestamp.isoformat(),
        }
        
        if not self.success and self.error:
            log_data["error"] = self.error
            logger.error("function_call_failed", **log_data)
        else:
            logger.info("function_call_succeeded", **log_data)
    
    def get_performance_metrics(self) -> dict[str, Any]:
        return {
            "function": self.function,
            "execution_time_ms": self.execution_time_ms,
            "success": self.success,
            "correlation_id": self.correlation_id,
            "timestamp": self.response_timestamp.isoformat(),
        }
