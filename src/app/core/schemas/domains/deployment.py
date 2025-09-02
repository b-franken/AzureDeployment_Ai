from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from app.core.schemas.base import AuditedSchema, BaseSchema, TimestampedSchema
from app.core.schemas.mixins import AzureMixin, ValidationMixin
from app.core.schemas.registry import register_schema


class DeploymentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@register_schema(version="1.0.0", category="deployment")
class DeploymentRequest(BaseSchema, AzureMixin, ValidationMixin):
    name: str = Field(description="Deployment name")
    template_type: str = Field(description="Template format (bicep, terraform, arm)")
    template_content: str = Field(description="Template content")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Template parameters")
    dry_run: bool = Field(default=True, description="Execute in dry-run mode")
    timeout_minutes: int = Field(default=60, ge=1, le=720, description="Deployment timeout")


@register_schema(version="1.0.0", category="deployment")
class DeploymentResponse(AuditedSchema):
    deployment_id: str = Field(description="Unique deployment identifier")
    status: DeploymentStatus = Field(description="Current deployment status")
    resource_count: int = Field(default=0, description="Number of resources deployed")
    outputs: dict[str, Any] = Field(default_factory=dict, description="Deployment outputs")
    error_details: list[str] = Field(default_factory=list, description="Error messages")
    warnings: list[str] = Field(default_factory=list, description="Warning messages")
    deployment_url: str | None = Field(default=None, description="Azure portal deployment URL")


@register_schema(version="1.0.0", category="deployment")
class DeploymentEvent(TimestampedSchema):
    type: str = Field(description="Event type (log, complete, error)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event payload data")
    timestamp: datetime = Field(description="Event timestamp")
