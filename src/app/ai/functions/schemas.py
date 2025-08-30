from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import Field
from app.core.schemas.base import BaseSchema, TimestampedSchema
from app.core.schemas.mixins import AzureMixin, ValidationMixin, CacheMixin
from app.core.schemas.registry import register_schema


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
    location: str = Field(default="westeurope", description="Azure region")
    resource_group: str = Field(description="Target resource group")
    environment: Literal["dev", "tst", "acc", "prod"] = Field(default="dev", description="Deployment environment")
    sku: Optional[str] = Field(default=None, description="Resource SKU/tier")
    configuration: dict[str, Any] = Field(default_factory=dict, description="Additional configuration parameters")
    tags: dict[str, str] = Field(default_factory=dict, description="Resource tags")


@register_schema(version="1.0.0", category="azure_functions")
class DeploymentPlan(BaseSchema, CacheMixin):
    resources: list[ResourceRequirements] = Field(description="Resources to deploy")
    deployment_order: list[str] = Field(description="Ordered list of resource names for deployment")
    parallel_groups: list[list[str]] = Field(default_factory=list, description="Groups of resources that can be deployed in parallel")
    estimated_time_minutes: int = Field(description="Estimated deployment time in minutes")
    prerequisites: list[str] = Field(default_factory=list, description="Prerequisites that must exist")
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
class DeploymentCostAnalysis(BaseSchema, CacheMixin):
    total_monthly_cost_usd: float = Field(description="Total estimated monthly cost")
    resources: list[CostEstimate] = Field(description="Per-resource cost breakdown")
    cost_optimization_suggestions: list[str] = Field(default_factory=list, description="Cost optimization recommendations")
    budget_alerts: list[str] = Field(default_factory=list, description="Budget warning messages")


@register_schema(version="1.0.0", category="azure_functions")
class ResourceDependency(BaseSchema):
    resource_name: str = Field(description="Resource name")
    depends_on: list[str] = Field(description="List of resources this depends on")
    deployment_group: int = Field(description="Deployment group number")
    estimated_deploy_time_minutes: int = Field(description="Estimated deployment time")


@register_schema(version="1.0.0", category="azure_functions")
class DependencyAnalysis(BaseSchema, CacheMixin):
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
    suggestion: Optional[str] = Field(default=None, description="Suggested fix")


@register_schema(version="1.0.0", category="azure_functions")
class ValidationResult(BaseSchema, ValidationMixin):
    is_valid: bool = Field(description="Whether configuration is valid")
    issues: list[ValidationIssue] = Field(description="Validation issues found")
    compliance_checks: dict[str, bool] = Field(default_factory=dict, description="Security and compliance validation")
    best_practices: list[str] = Field(default_factory=list, description="Best practice recommendations")


@register_schema(version="1.0.0", category="azure_functions")
class ResourceRecommendation(BaseSchema, AzureMixin):
    resource_type: str = Field(description="Recommended resource type")
    resource_name: str = Field(description="Suggested resource name")
    rationale: str = Field(description="Why this resource is recommended")
    priority: Literal["high", "medium", "low"] = Field(description="Recommendation priority")
    estimated_cost_impact: str = Field(description="Cost impact estimate")
    configuration: dict[str, Any] = Field(default_factory=dict, description="Recommended configuration")


@register_schema(version="1.0.0", category="azure_functions")
class ResourceRecommendations(BaseSchema, CacheMixin):
    primary_resource: str = Field(description="Primary resource being analyzed")
    recommendations: list[ResourceRecommendation] = Field(description="List of recommended resources")
    architecture_patterns: list[str] = Field(default_factory=list, description="Suggested architecture patterns")
    security_enhancements: list[str] = Field(default_factory=list, description="Security recommendations")


@register_schema(version="1.0.0", category="azure_functions")
class FunctionCallRequest(TimestampedSchema):
    function: FunctionCallType = Field(description="Function to call")
    arguments: dict[str, Any] = Field(description="Function arguments")
    correlation_id: str = Field(description="Request correlation ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


@register_schema(version="1.0.0", category="azure_functions")
class FunctionCallResponse(TimestampedSchema):
    function: FunctionCallType = Field(description="Function that was called")
    success: bool = Field(description="Whether function call succeeded")
    result: Any = Field(description="Function result data")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    execution_time_ms: float = Field(description="Execution time in milliseconds")
    correlation_id: str = Field(description="Request correlation ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))