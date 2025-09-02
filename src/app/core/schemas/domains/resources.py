from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.core.schemas.base import BaseSchema
from app.core.schemas.mixins import AzureMixin, ValidationMixin
from app.core.schemas.registry import register_schema


@register_schema(version="1.0.0", category="azure_resources")
class AzureResource(BaseSchema, AzureMixin, ValidationMixin):
    resource_id: str = Field(description="Azure resource ID")
    resource_type: str = Field(description="Type of Azure resource")
    resource_name: str = Field(description="Name of the resource")
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Resource-specific properties"
    )
    sku: str | None = Field(default=None, description="Resource SKU/pricing tier")
    status: Literal["creating", "running", "stopped", "failed", "deleting"] = Field(
        default="creating", description="Resource status"
    )


@register_schema(version="1.0.0", category="azure_resources")
class ResourceRequirements(BaseSchema, AzureMixin, ValidationMixin):
    resource_type: str = Field(description="Type of Azure resource")
    resource_name: str = Field(description="Name of the resource")
    sku: str | None = Field(default=None, description="Resource SKU/tier")
    configuration: dict[str, Any] = Field(
        default_factory=dict, description="Additional configuration parameters"
    )


@register_schema(version="1.0.0", category="azure_resources")
class ResourceDependency(BaseSchema):
    resource_name: str = Field(description="Resource name")
    depends_on: list[str] = Field(description="List of resources this depends on")
    deployment_group: int = Field(description="Deployment group number")
    estimated_deploy_time_minutes: int = Field(description="Estimated deployment time")
    dependency_type: Literal["hard", "soft", "optional"] = Field(
        default="hard", description="Type of dependency"
    )
    reason: str | None = Field(default=None, description="Reason for the dependency")
