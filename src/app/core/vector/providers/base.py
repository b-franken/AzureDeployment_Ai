from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import Field

from app.core.schemas.base import BaseSchema

tracer = trace.get_tracer(__name__)


class VectorQuery(BaseSchema):
    query_text: str
    query_vector: list[float] | None = None
    filter_criteria: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=10, ge=1, le=1000)
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    include_metadata: bool = True
    namespace: str | None = None


class VectorSearchResult(BaseSchema):
    id: str
    content: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None
    namespace: str | None = None


class VectorSearchResponse(BaseSchema):
    query: VectorQuery
    results: list[VectorSearchResult]
    total_found: int
    search_time_ms: float
    provider: str


class VectorProvider(ABC):
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.name = self.__class__.__name__
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> None:
        pass

    @abstractmethod
    async def create_collection(
        self, collection_name: str, dimension: int, metadata: dict[str, Any] | None = None
    ) -> bool:
        pass

    @abstractmethod
    async def delete_collection(self, collection_name: str) -> bool:
        pass

    @abstractmethod
    async def list_collections(self) -> list[str]:
        pass

    @abstractmethod
    async def upsert_vectors(self, collection_name: str, vectors: list[dict[str, Any]]) -> bool:
        pass

    @abstractmethod
    async def delete_vectors(self, collection_name: str, vector_ids: list[str]) -> bool:
        pass

    @abstractmethod
    async def search_similar(
        self, collection_name: str, query: VectorQuery
    ) -> VectorSearchResponse:
        pass

    @abstractmethod
    async def get_vector_by_id(
        self, collection_name: str, vector_id: str
    ) -> VectorSearchResult | None:
        pass

    async def health_check(self) -> dict[str, Any]:
        with tracer.start_as_current_span("vector_provider_health_check") as span:
            span.set_attributes(
                {"provider.name": self.name, "provider.initialized": self._initialized}
            )

            try:
                collections = await self.list_collections()
                health_status = {
                    "provider": self.name,
                    "status": "healthy",
                    "initialized": self._initialized,
                    "collections_count": len(collections),
                    "timestamp": datetime.now(UTC).isoformat(),
                }

                span.set_attributes(
                    {"health.status": "healthy", "health.collections_count": len(collections)}
                )
                span.set_status(Status(StatusCode.OK))

                return health_status

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))

                return {
                    "provider": self.name,
                    "status": "unhealthy",
                    "error": str(e),
                    "initialized": self._initialized,
                    "timestamp": datetime.now(UTC).isoformat(),
                }

    async def get_stats(self, collection_name: str) -> dict[str, Any]:
        with tracer.start_as_current_span("vector_provider_stats") as span:
            span.set_attributes({"provider.name": self.name, "collection.name": collection_name})

            base_stats = {
                "provider": self.name,
                "collection": collection_name,
                "timestamp": datetime.now(UTC).isoformat(),
            }

            try:
                collections = await self.list_collections()
                if collection_name not in collections:
                    span.set_status(Status(StatusCode.ERROR, "Collection not found"))
                    return {**base_stats, "error": "Collection not found"}

                span.set_status(Status(StatusCode.OK))
                return base_stats

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return {**base_stats, "error": str(e)}

    def __repr__(self) -> str:
        return f"{self.name}(initialized={self._initialized})"
