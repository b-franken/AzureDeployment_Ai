from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LLMProvider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"
    OLLAMA = "ollama"


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class LLMMessage(BaseModel):
    role: MessageRole
    content: str
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: Any) -> str:
        if v is None:
            return ""
        if not isinstance(v, str):
            try:
                import json

                return json.dumps(v, ensure_ascii=False)
            except Exception:
                return str(v)
        return v


class LLMRequest(BaseModel):
    model: str
    messages: list[LLMMessage]
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32000)
    stream: bool = False

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: list[LLMMessage]) -> list[LLMMessage]:
        if not v:
            raise ValueError("Messages cannot be empty")
        return v


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMChoice(BaseModel):
    index: int
    message: LLMMessage
    finish_reason: str | None = None


class LLMResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(datetime.now(UTC).timestamp()))
    model: str
    choices: list[LLMChoice]
    usage: LLMUsage | None = None

    @property
    def text(self) -> str:
        if self.choices:
            return self.choices[0].message.content
        return ""

    @property
    def success(self) -> bool:
        return bool(self.choices and self.choices[0].message.content.strip())


class LLMStreamChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(datetime.now(UTC).timestamp()))
    model: str
    choices: list[dict[str, Any]]

    @property
    def content(self) -> str:
        if self.choices:
            delta = self.choices[0].get("delta", {})
            content = delta.get("content", "")
            return content if isinstance(content, str) else ""
        return ""


class LLMError(BaseModel):
    error: dict[str, Any]

    @property
    def message(self) -> str:
        msg = self.error.get("message", "Unknown LLM error")
        return msg if isinstance(msg, str) else "Unknown LLM error"

    @property
    def type(self) -> str:
        type_val = self.error.get("type", "unknown")
        return type_val if isinstance(type_val, str) else "unknown"

    @property
    def code(self) -> str:
        code_val = self.error.get("code", "unknown")
        return code_val if isinstance(code_val, str) else "unknown"


class ValidationResult(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sanitized_messages: list[LLMMessage] = Field(default_factory=list)

    @classmethod
    def success(cls, sanitized: list[LLMMessage]) -> ValidationResult:
        return cls(is_valid=True, sanitized_messages=sanitized)

    @classmethod
    def failure(cls, errors: list[str], warnings: list[str] | None = None) -> ValidationResult:
        return cls(is_valid=False, errors=errors, warnings=warnings or [], sanitized_messages=[])
