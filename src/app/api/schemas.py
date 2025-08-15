from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field


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


class ReviewRequest(BaseModel):
    user_input: str = Field(..., min_length=1)
    assistant_reply: str = Field(..., min_length=1)
    provider: str | None = None
    model: str | None = None


class ReviewResponse(BaseModel):
    output: str
