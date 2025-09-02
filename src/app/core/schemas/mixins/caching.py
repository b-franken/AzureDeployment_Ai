from __future__ import annotations

import hashlib
import json
from typing import Any, ClassVar, Protocol

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer(__name__)


class BaseModelProtocol(Protocol):
    _cache_ttl: int
    _cache_excluded_fields: set[str]

    def model_dump(
        self, *, exclude: set[str] | None = None, exclude_none: bool = False
    ) -> dict[str, Any]: ...


class CacheMixin:
    _cache_ttl: ClassVar[int] = 300
    _cache_excluded_fields: ClassVar[set[str]] = {"correlation_id", "created_at", "updated_at"}

    def get_cache_key(self: BaseModelProtocol, prefix: str = "") -> str:
        with tracer.start_as_current_span("schema_cache_key_generation") as span:
            span.set_attributes(
                {
                    "schema.name": self.__class__.__name__,
                    "cache.prefix": prefix,
                    "cache.excluded_fields": list(self._cache_excluded_fields),
                }
            )

            cache_data = self.model_dump(exclude=self._cache_excluded_fields, exclude_none=True)
            content = json.dumps(cache_data, sort_keys=True, default=str)
            key_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            cache_key = (
                f"{prefix}:{self.__class__.__name__}:{key_hash}"
                if prefix
                else f"{self.__class__.__name__}:{key_hash}"
            )

            span.set_attributes({"cache.key": cache_key, "cache.data_size": len(content)})
            span.set_status(Status(StatusCode.OK))
            return cache_key

    def get_cache_metadata(self: BaseModelProtocol) -> dict[str, Any]:
        with tracer.start_as_current_span("schema_cache_metadata") as span:
            metadata = {
                "ttl": self._cache_ttl,
                "schema": self.__class__.__name__,
                "version": getattr(self, "_schema_version", "1.0.0"),
                "excluded_fields": list(self._cache_excluded_fields),
            }

            span.set_attributes(
                {"schema.name": self.__class__.__name__, "cache.ttl": self._cache_ttl}
            )
            span.set_status(Status(StatusCode.OK))
            return metadata

    @classmethod
    def set_cache_ttl(cls, ttl: int) -> None:
        with tracer.start_as_current_span("schema_set_cache_ttl") as span:
            cls._cache_ttl = ttl
            span.set_attributes({"schema.name": cls.__name__, "cache.ttl": ttl})
            span.set_status(Status(StatusCode.OK))

    @classmethod
    def exclude_from_cache(cls, *field_names: str) -> None:
        with tracer.start_as_current_span("schema_cache_exclusions") as span:
            cls._cache_excluded_fields.update(field_names)
            span.set_attributes(
                {
                    "schema.name": cls.__name__,
                    "cache.new_exclusions": list(field_names),
                    "cache.total_exclusions": len(cls._cache_excluded_fields),
                }
            )
            span.set_status(Status(StatusCode.OK))

    def cache_fingerprint(self: BaseModelProtocol) -> str:
        with tracer.start_as_current_span("schema_cache_fingerprint") as span:
            relevant_data = {
                k: v for k, v in self.model_dump().items() if k not in self._cache_excluded_fields
            }
            fingerprint = hashlib.md5(
                json.dumps(relevant_data, sort_keys=True, default=str).encode()
            ).hexdigest()

            span.set_attributes(
                {
                    "schema.name": self.__class__.__name__,
                    "fingerprint.hash": fingerprint[:8],
                    "fingerprint.data_fields": len(relevant_data),
                }
            )
            span.set_status(Status(StatusCode.OK))
            return fingerprint
