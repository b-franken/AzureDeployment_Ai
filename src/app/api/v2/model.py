from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, validator


class token_data(BaseModel):
    user_id: str
    email: str
    subscription_id: str | None = None
    roles: list[str] = Field(default_factory=list)
    expires_at: datetime


class auth_request(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8)
    mfa_code: str | None = None


class chat_request_v2(BaseModel):
    input: str = Field(..., min_length=1, max_length=5000)
    memory: list[dict[str, str]] | None = None
    provider: str | None = None
    model: str | None = None
    enable_tools: bool = True
    dry_run: bool = True
    environment: str = "development"
    correlation_id: str | None = None

    @validator("environment")
    def validate_environment(cls, v: str) -> str:
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(
                "environment must be one of development, staging, production"
            )
        return v


class deploy_request_v2(BaseModel):
    request: str = Field(..., min_length=1, max_length=5000)
    subscription_id: str = Field(..., pattern=r"^[a-f0-9-]{36}$")
    resource_group: str | None = None
    environment: str = "development"
    dry_run: bool = True
    approval_required: bool = True
    cost_limit: float | None = Field(default=None, ge=0)
    tags: dict[str, str] = Field(default_factory=dict)

    @validator("environment")
    def validate_environment(cls, v: str) -> str:
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(
                "environment must be one of development, staging, production"
            )
        return v


class cost_analysis_request_v2(BaseModel):
    subscription_id: str = Field(..., pattern=r"^[a-f0-9-]{36}$")
    start_date: datetime
    end_date: datetime
    group_by: list[str] | None = None
    include_forecast: bool = False
    include_recommendations: bool = False
