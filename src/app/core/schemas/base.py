from __future__ import annotations

import hashlib
import json
import uuid
from abc import ABC
from datetime import UTC, datetime
from typing import Any, ClassVar, Generic, TypeVar, Self

import structlog
from pydantic import BaseModel, Field, ConfigDict, computed_field, field_serializer

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class BaseSchema(BaseModel, ABC):
    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
        use_enum_values=True,
        str_strip_whitespace=True,
        validate_default=True,
        extra="forbid",
        arbitrary_types_allowed=False,
    )
    
    _schema_version: ClassVar[str] = "1.0.0"
    _schema_name: ClassVar[str] = ""
    
    correlation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Request correlation identifier"
    )
    
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._schema_name = cls.__name__
        logger.debug(
            "schema_registered",
            schema_name=cls._schema_name,
            schema_version=cls._schema_version,
            module=cls.__module__
        )
    
    @computed_field
    @property
    def schema_metadata(self) -> dict[str, Any]:
        return {
            "name": self._schema_name,
            "version": self._schema_version,
            "module": self.__class__.__module__,
        }
    
    def get_cache_key(self) -> str:
        data = self.model_dump(exclude={"correlation_id"})
        content = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def log_validation_success(self) -> Self:
        logger.info(
            "schema_validation_success",
            schema_name=self._schema_name,
            correlation_id=self.correlation_id
        )
        return self
    
    def log_validation_error(self, error: Exception) -> None:
        logger.error(
            "schema_validation_error",
            schema_name=self._schema_name,
            correlation_id=self.correlation_id,
            error=str(error),
            error_type=type(error).__name__
        )


class TimestampedSchema(BaseSchema):
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last update timestamp"
    )
    
    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return value.isoformat()
    
    def update_timestamp(self) -> Self:
        self.updated_at = datetime.now(UTC)
        logger.debug(
            "schema_timestamp_updated",
            schema_name=self._schema_name,
            correlation_id=self.correlation_id,
            updated_at=self.updated_at.isoformat()
        )
        return self


class AuditedSchema(TimestampedSchema):
    created_by: str | None = Field(default=None, description="Creator identifier")
    updated_by: str | None = Field(default=None, description="Last updater identifier")
    version: int = Field(default=1, description="Record version")
    
    def audit_update(self, user_id: str) -> Self:
        self.updated_by = user_id
        self.version += 1
        self.update_timestamp()
        logger.info(
            "schema_audit_update",
            schema_name=self._schema_name,
            correlation_id=self.correlation_id,
            updated_by=user_id,
            version=self.version
        )
        return self


class PaginatedResponse(BaseSchema, Generic[T]):
    items: list[T] = Field(description="Response items")
    total: int = Field(description="Total item count")
    page: int = Field(ge=1, description="Current page number")
    page_size: int = Field(ge=1, le=1000, description="Items per page")
    has_next: bool = Field(description="Has next page")
    has_previous: bool = Field(description="Has previous page")
    
    @computed_field
    @property
    def total_pages(self) -> int:
        return (self.total + self.page_size - 1) // self.page_size