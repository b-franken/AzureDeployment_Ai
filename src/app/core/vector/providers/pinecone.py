from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .base import VectorProvider, VectorQuery, VectorSearchResponse, VectorSearchResult

if TYPE_CHECKING:
    from typing import Protocol

    class PineconeModule(Protocol):
        def init(self, api_key: str, environment: str) -> None: ...
        def create_index(
            self,
            name: str,
            dimension: int,
            metric: str,
            replicas: int,
            metadata_config: dict[str, Any],
        ) -> None: ...
        def delete_index(self, name: str) -> None: ...
        def list_indexes(self) -> list[str]: ...
        def Index(self, name: str) -> Any: ...

    class PineconeIndex(Protocol):
        def upsert(self, vectors: list[dict[str, Any]], namespace: str | None = None) -> None: ...
        def delete(self, ids: list[str]) -> None: ...
        def query(self, **kwargs: Any) -> Any: ...
        def fetch(self, ids: list[str], include_metadata: bool = True) -> Any: ...
        def describe_index_stats(self) -> Any: ...


def _import_pinecone() -> Any:
    """Dynamically import pinecone to handle optional dependency."""
    try:
        return importlib.import_module("pinecone")
    except ImportError as e:
        raise ImportError(
            "pinecone-client is required but not installed. "
            "Install it with: pip install pinecone-client"
        ) from e


_pinecone_module: Any = None

tracer = trace.get_tracer(__name__)


class PineconeProvider(VectorProvider):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._client: Any = None
        self._indexes: dict[str, Any] = {}

        # Pinecone will be imported dynamically when needed

    async def initialize(self) -> None:
        with tracer.start_as_current_span("pinecone_initialize") as span:
            try:
                global _pinecone_module
                if _pinecone_module is None:
                    _pinecone_module = _import_pinecone()

                api_key = self.config.get("api_key")
                environment = self.config.get("environment", "us-east-1")

                if not api_key:
                    raise ValueError("Pinecone API key is required")

                _pinecone_module.init(api_key=api_key, environment=environment)
                self._client = _pinecone_module
                self._initialized = True

                span.set_attributes(
                    {"pinecone.environment": environment, "pinecone.initialized": True}
                )
                span.set_status(Status(StatusCode.OK))

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    async def create_collection(
        self, collection_name: str, dimension: int, metadata: dict[str, Any] | None = None
    ) -> bool:
        with tracer.start_as_current_span("pinecone_create_index") as span:
            span.set_attributes({"index.name": collection_name, "index.dimension": dimension})

            try:
                metric = metadata.get("metric", "cosine") if metadata else "cosine"
                replicas = metadata.get("replicas", 1) if metadata else 1

                self._client.create_index(
                    name=collection_name,
                    dimension=dimension,
                    metric=metric,
                    replicas=replicas,
                    metadata_config={
                        "indexed": metadata.get("indexed_fields", []) if metadata else []
                    },
                )

                index = self._client.Index(collection_name)
                self._indexes[collection_name] = index

                span.set_attributes(
                    {"index.created": True, "index.metric": metric, "index.replicas": replicas}
                )
                span.set_status(Status(StatusCode.OK))

                return True

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False

    async def delete_collection(self, collection_name: str) -> bool:
        with tracer.start_as_current_span("pinecone_delete_index") as span:
            span.set_attribute("index.name", collection_name)

            try:
                self._client.delete_index(collection_name)
                self._indexes.pop(collection_name, None)

                span.set_attribute("index.deleted", True)
                span.set_status(Status(StatusCode.OK))

                return True

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False

    async def list_collections(self) -> list[str]:
        with tracer.start_as_current_span("pinecone_list_indexes") as span:
            try:
                indexes = self._client.list_indexes()

                span.set_attributes({"indexes.count": len(indexes), "indexes.names": indexes})
                span.set_status(Status(StatusCode.OK))

                return cast(list[str], indexes)

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return []

    async def upsert_vectors(self, collection_name: str, vectors: list[dict[str, Any]]) -> bool:
        with tracer.start_as_current_span("pinecone_upsert_vectors") as span:
            span.set_attributes({"index.name": collection_name, "vectors.count": len(vectors)})

            try:
                index = self._get_index(collection_name)

                upsert_data = []
                for vector in vectors:
                    metadata = vector.get("metadata", {})
                    if "content" in vector:
                        metadata["content"] = vector["content"]

                    upsert_data.append(
                        {"id": vector["id"], "values": vector["embedding"], "metadata": metadata}
                    )

                batch_size = 100
                for i in range(0, len(upsert_data), batch_size):
                    batch = upsert_data[i : i + batch_size]
                    index.upsert(vectors=batch, namespace=vectors[0].get("namespace"))

                span.set_attributes(
                    {
                        "upsert.success": True,
                        "upsert.batches": (len(upsert_data) + batch_size - 1) // batch_size,
                    }
                )
                span.set_status(Status(StatusCode.OK))

                return True

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False

    async def delete_vectors(self, collection_name: str, vector_ids: list[str]) -> bool:
        with tracer.start_as_current_span("pinecone_delete_vectors") as span:
            span.set_attributes(
                {"index.name": collection_name, "vector_ids.count": len(vector_ids)}
            )

            try:
                index = self._get_index(collection_name)
                index.delete(ids=vector_ids)

                span.set_attributes({"delete.success": True, "delete.count": len(vector_ids)})
                span.set_status(Status(StatusCode.OK))

                return True

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return False

    async def search_similar(
        self, collection_name: str, query: VectorQuery
    ) -> VectorSearchResponse:
        start_time = datetime.now(UTC)

        with tracer.start_as_current_span("pinecone_search_similar") as span:
            span.set_attributes(
                {
                    "index.name": collection_name,
                    "query.limit": query.limit,
                    "query.threshold": query.threshold,
                    "query.has_vector": query.query_vector is not None,
                    "query.namespace": query.namespace or "",
                }
            )

            try:
                if not query.query_vector:
                    raise ValueError("Pinecone requires query_vector for search")

                index = self._get_index(collection_name)

                search_kwargs = {
                    "vector": query.query_vector,
                    "top_k": query.limit,
                    "include_metadata": query.include_metadata,
                    "include_values": False,
                    "namespace": query.namespace,
                }

                if query.filter_criteria:
                    search_kwargs["filter"] = query.filter_criteria

                response = index.query(**search_kwargs)

                search_results = []
                for match in response.matches:
                    if match.score >= query.threshold:
                        metadata = match.metadata or {}
                        content = metadata.pop("content", "")

                        result = VectorSearchResult(
                            id=match.id,
                            content=content,
                            score=match.score,
                            metadata=metadata,
                            namespace=query.namespace,
                        )
                        search_results.append(result)

                search_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

                search_response = VectorSearchResponse(
                    query=query,
                    results=search_results,
                    total_found=len(search_results),
                    search_time_ms=search_time,
                    provider="PineconeProvider",
                )

                span.set_attributes(
                    {
                        "search.results_count": len(search_results),
                        "search.time_ms": search_time,
                        "search.success": True,
                    }
                )
                span.set_status(Status(StatusCode.OK))

                return search_response

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))

                search_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                return VectorSearchResponse(
                    query=query,
                    results=[],
                    total_found=0,
                    search_time_ms=search_time,
                    provider="PineconeProvider",
                )

    async def get_vector_by_id(
        self, collection_name: str, vector_id: str
    ) -> VectorSearchResult | None:
        with tracer.start_as_current_span("pinecone_get_vector_by_id") as span:
            span.set_attributes({"index.name": collection_name, "vector.id": vector_id})

            try:
                index = self._get_index(collection_name)

                response = index.fetch(ids=[vector_id], include_metadata=True)

                if vector_id in response.vectors:
                    vector_data = response.vectors[vector_id]
                    metadata = vector_data.metadata or {}
                    content = metadata.pop("content", "")

                    result = VectorSearchResult(
                        id=vector_id,
                        content=content,
                        score=1.0,
                        metadata=metadata,
                        embedding=vector_data.values if hasattr(vector_data, "values") else None,
                    )

                    span.set_attribute("vector.found", True)
                    span.set_status(Status(StatusCode.OK))

                    return result
                else:
                    span.set_attribute("vector.found", False)
                    span.set_status(Status(StatusCode.OK))
                    return None

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return None

    def _get_index(self, collection_name: str) -> Any:
        if collection_name not in self._indexes:
            try:
                self._indexes[collection_name] = self._client.Index(collection_name)
            except Exception as e:
                raise ValueError(f"Index {collection_name} not found") from e

        return self._indexes[collection_name]

    async def get_stats(self, collection_name: str) -> dict[str, Any]:
        with tracer.start_as_current_span("pinecone_get_stats") as span:
            span.set_attributes({"provider.name": self.name, "index.name": collection_name})

            try:
                index = self._get_index(collection_name)
                stats = index.describe_index_stats()

                result = {
                    "provider": self.name,
                    "collection": collection_name,
                    "total_vector_count": stats.total_vector_count,
                    "dimension": stats.dimension,
                    "index_fullness": stats.index_fullness,
                    "namespaces": dict(stats.namespaces) if stats.namespaces else {},
                    "timestamp": datetime.now(UTC).isoformat(),
                }

                span.set_attributes(
                    {
                        "stats.total_vectors": stats.total_vector_count,
                        "stats.dimension": stats.dimension,
                        "stats.index_fullness": stats.index_fullness,
                    }
                )
                span.set_status(Status(StatusCode.OK))

                return result

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return {
                    "provider": self.name,
                    "collection": collection_name,
                    "error": str(e),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
