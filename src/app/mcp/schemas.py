from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Environment(str, Enum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


class ToolExecutionRequest(BaseModel):
    tool_name: str
    input_text: str
    memory: list[dict[str, str]] | None = None
    provider: str | None = None
    model: str | None = None
    subscription_id: str | None = None
    resource_group: str | None = None
    environment: Literal["dev", "test", "staging", "prod"] = "dev"
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    audit_enabled: bool = True
    cost_limit: int | None = None
    dry_run: bool = True
    cache_ttl: int = 300
    force_refresh: bool = False

    def get_cache_key(self) -> str:
        data = {
            "tool": self.tool_name,
            "input": self.input_text,
            "env": self.environment,
            "dry_run": self.dry_run,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


class ToolExecutionResponse(BaseModel):
    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    execution_time: datetime
    correlation_id: str
    cached: bool = False


class DeploymentRequest(BaseModel):
    deployment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    product: str
    environment: Environment
    subscription_id: str
    resource_group: str
    location: str = "westeurope"
    resources: list[dict[str, Any]]
    parameters: dict[str, Any]
    tags: dict[str, str] = Field(default_factory=dict)
    validate_only: bool = False
    require_approval: bool = True
    approval_token: str | None = None
    continue_on_error: bool = False
    rollback_on_failure: bool = True
    timeout_minutes: int = 60


class AzureQueryParams(BaseModel):
    kql: str = Field(..., description="Kusto Query Language query")
    subscriptions: list[str] | None = None
    top: int | None = Field(None, ge=1, le=1000)
    skip: int | None = Field(None, ge=0)
    skip_token: str | None = None
    include_facets: bool = False
    cache_ttl: int = 300
    force_refresh: bool = False

    @field_validator("kql")
    @classmethod
    def validate_kql(cls, v: str) -> str:
        dangerous_ops = ["| take", "| sample"]
        v_lower = v.lower()
        for op in dangerous_ops:
            if op in v_lower:
                raise ValueError(f"Use 'order by' and 'limit' instead of {op}")
        return v

    def get_cache_key(self) -> str:
        data = {
            "kql": self.kql,
            "subs": sorted(self.subscriptions or []),
            "top": self.top,
            "skip": self.skip,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


class ResourceQueryRequest(BaseModel):
    resource_type: str | None = None
    resource_group: str | None = None
    tags: dict[str, str] | None = None
    location: str | None = None
    include_costs: bool = False
    include_metrics: bool = False


class CostAnalysisRequest(BaseModel):
    subscription_id: str
    start_date: datetime
    end_date: datetime
    granularity: Literal["daily", "monthly"] = "monthly"
    group_by: list[str] | None = None
    include_forecast: bool = False
    include_recommendations: bool = False


__all__ = [
    "Environment",
    "ToolExecutionRequest",
    "ToolExecutionResponse",
    "DeploymentRequest",
    "AzureQueryParams",
    "ResourceQueryRequest",
    "CostAnalysisRequest",
]
