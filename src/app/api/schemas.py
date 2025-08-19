from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    input: str = Field(..., min_length=1)
    memory: Sequence[ChatMessage] | None = None
    provider: str | None = None
    model: str | None = None
    enable_tools: bool = False
    preferred_tool: str | None = None
    allowlist: Sequence[str] | None = None


class ChatResponse(BaseModel):
    output: str


class ChatRequestV2(BaseModel):
    input: str = Field(min_length=1, max_length=5000)
    memory: list[dict[str, str]] | None = None
    provider: str | None = None
    model: str | None = None
    enable_tools: bool = True
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ReviewRequest(BaseModel):
    user_input: str = Field(..., min_length=1)
    assistant_reply: str = Field(..., min_length=1)
    provider: str | None = None
    model: str | None = None


class ReviewResponse(BaseModel):
    output: str


class TokenData(BaseModel):
    user_id: str
    email: str
    subscription_id: str | None = None
    roles: list[str] = Field(default_factory=list)
    expires_at: datetime


class AuthRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8)
    mfa_code: str | None = None


class DeploymentRequest(BaseModel):
    request: str = Field(..., min_length=1, max_length=5000)
    subscription_id: str = Field(..., pattern=r"^[a-f0-9-]{36}$")
    resource_group: str | None = None
    environment: str = "development"
    dry_run: bool = True
    cost_limit: float | None = Field(default=None, ge=0)
    tags: dict[str, str] = Field(default_factory=dict)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError("environment must be one of development, staging, production")
        return v


class CostAnalysisRequest(BaseModel):
    subscription_id: str
    start_date: datetime
    end_date: datetime
    group_by: list[str] | None = None
    include_forecast: bool = False
    include_recommendations: bool = False


class LogsResponse(BaseModel):
    logs: list[dict[str, Any]]
    count: int


class CostAnalysisResponse(BaseModel):
    analysis: dict[str, Any]
    forecast: dict[str, Any] | None = None
    recommendations: list[dict[str, Any]] | None = None


class StructuredChatRequest(BaseModel):
    input: str = Field(..., min_length=1)
    schema_: dict[str, Any] = Field(
        ...,
        description="JSON Schema for the expected output",
        validation_alias="schema",
        serialization_alias="schema",
    )
    provider: str | None = None
    model: str | None = None


class StructuredChatResponse(BaseModel):
    response: dict[str, Any]


__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ChatRequestV2",
    "ReviewRequest",
    "ReviewResponse",
    "TokenData",
    "AuthRequest",
    "DeploymentRequest",
    "CostAnalysisRequest",
    "LogsResponse",
    "CostAnalysisResponse",
    "StructuredChatRequest",
    "StructuredChatResponse",
]
