from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.logging import get_logger
from app.core.plugins.base import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginMetadata,
    PluginResult,
    PluginType,
)
from app.core.vector.registry import VectorRegistry
from app.core.vector.semantic.indexer import ResourceIndexer
from app.core.vector.semantic.matcher import SemanticMatcher
from app.memory.agent_persistence import get_agent_memory
from app.observability.app_insights import app_insights
from app.observability.distributed_tracing import get_service_tracer

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)


class VectorDatabasePlugin(Plugin):
    def __init__(self, config: PluginConfig):
        metadata = PluginMetadata(
            name="vector_database",
            version="1.0.0",
            description="Vector database integration for semantic search and RAG capabilities",
            author="Azure Deployment AI",
            plugin_type=PluginType.PROVIDER,
            dependencies=[],
            configuration_schema={
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "enum": ["chroma", "pinecone", "azure_search"],
                        "default": "chroma",
                    },
                    "embedding_model": {"type": "string", "default": "text-embedding-3-small"},
                    "dimension": {"type": "integer", "default": 1536},
                    "connection_config": {
                        "type": "object",
                        "properties": {
                            "host": {"type": "string"},
                            "port": {"type": "integer"},
                            "api_key": {"type": "string"},
                            "index_name": {"type": "string"},
                        },
                    },
                    "auto_index_resources": {"type": "boolean", "default": True},
                    "cache_ttl_hours": {"type": "integer", "default": 24},
                },
                "required": ["provider"],
            },
        )

        super().__init__(metadata, config)

        self.vector_registry: VectorRegistry | None = None
        self.semantic_matcher: SemanticMatcher | None = None
        self.resource_indexer: ResourceIndexer | None = None
        self.service_tracer = get_service_tracer("vector_database_plugin")
        self.logger = logger.bind(component="vector_plugin")

        self._embedding_cache: dict[str, Any] = {}
        self._cache_timestamps: dict[str, datetime] = {}

    async def initialize(self) -> None:
        async with self.service_tracer.start_distributed_span(
            operation_name="vector_plugin_initialize",
            correlation_id="vector_init",
            attributes={
                "plugin.name": self.metadata.name,
                "plugin.version": self.metadata.version,
                "provider": self.config.configuration.get("provider", "chroma"),
            },
        ) as span:
            try:
                provider = self.config.configuration.get("provider", "chroma")
                connection_config = self.config.configuration.get("connection_config", {})

                self.vector_registry = VectorRegistry()

                # Register the vector provider based on configuration
                if provider == "chroma":
                    from app.core.vector.providers.chroma import ChromaProvider

                    chroma_provider = ChromaProvider(connection_config)
                    await self.vector_registry.register_provider(
                        name="chroma",
                        provider=chroma_provider,
                        config=connection_config,
                        set_as_default=True,
                    )
                elif provider == "pinecone":
                    from app.core.vector.providers.pinecone import PineconeProvider

                    pinecone_provider = PineconeProvider(connection_config)
                    await self.vector_registry.register_provider(
                        name="pinecone",
                        provider=pinecone_provider,
                        config=connection_config,
                        set_as_default=True,
                    )

                # Get the default provider for semantic matching
                default_provider = self.vector_registry.get_provider()
                if not default_provider:
                    raise RuntimeError(f"No vector provider available for {provider}")

                self.semantic_matcher = SemanticMatcher(
                    vector_provider=default_provider, collection_name="azure_resources"
                )

                self.resource_indexer = ResourceIndexer(
                    vector_provider=default_provider,
                    collection_name="azure_resources",
                    embedding_dimension=self.config.configuration.get("dimension", 1536),
                )

                embedding_model = self.config.configuration.get("embedding_model")
                span.set_attributes(
                    {
                        "vector.provider": provider,
                        "vector.embedding_model": (
                            str(embedding_model) if embedding_model else "default"
                        ),
                        "vector.dimension": int(self.config.configuration.get("dimension", 1536)),
                        "vector.auto_index": bool(
                            self.config.configuration.get("auto_index_resources", True)
                        ),
                    }
                )

                app_insights.track_custom_event(
                    "vector_plugin_initialized",
                    {
                        "plugin_name": self.metadata.name,
                        "provider": provider,
                        "embedding_model": self.config.configuration.get("embedding_model"),
                    },
                    {"dimension": self.config.configuration.get("dimension", 1536)},
                )

                self.logger.info(
                    "Vector database plugin initialized",
                    provider=provider,
                    embedding_model=self.config.configuration.get("embedding_model"),
                )

                span.set_status(Status(StatusCode.OK))

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error("Failed to initialize vector plugin", error=str(e), exc_info=True)
                raise

    async def execute(self, context: PluginContext) -> PluginResult:
        async with self.service_tracer.start_distributed_span(
            operation_name="vector_plugin_execute",
            correlation_id=context.correlation_id,
            attributes={
                "plugin.name": self.metadata.name,
                "context.operation": context.execution_context.get("operation", "unknown"),
            },
        ) as span:
            start_time = datetime.now(UTC)
            operation = context.execution_context.get("operation", "search")

            try:
                result_data: dict[str, Any] | list[dict[str, Any]] | None = None
                warnings: list[str] = []

                if operation == "semantic_search":
                    result_data = await self._handle_semantic_search(context, span)
                elif operation == "index_resource":
                    result_data = await self._handle_resource_indexing(context, span)
                elif operation == "similarity_search":
                    result_data = await self._handle_similarity_search(context, span)
                elif operation == "get_relevant_context":
                    result_data = await self._handle_context_retrieval(context, span)
                elif operation == "cleanup_expired":
                    result_data = await self._handle_cleanup(context, span)
                else:
                    raise ValueError(f"Unsupported operation: {operation}")

                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

                span.set_attributes(
                    {
                        "vector.operation": operation,
                        "vector.execution_time_ms": execution_time,
                        "vector.success": True,
                    }
                )

                app_insights.track_custom_event(
                    "vector_operation_completed",
                    {
                        "plugin_name": self.metadata.name,
                        "operation": operation,
                        "correlation_id": context.correlation_id,
                    },
                    {
                        "execution_time_ms": execution_time,
                        "result_size": len(str(result_data)) if result_data else 0,
                    },
                )

                span.set_status(Status(StatusCode.OK))

                return PluginResult(
                    correlation_id=context.correlation_id,
                    success=True,
                    result=result_data,
                    warnings=warnings,
                    execution_time_ms=execution_time,
                    metadata={
                        "operation": operation,
                        "provider": self.config.configuration.get("provider"),
                    },
                )

            except Exception as e:
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))

                app_insights.track_exception(
                    e,
                    {
                        "plugin_name": self.metadata.name,
                        "operation": operation,
                        "correlation_id": context.correlation_id,
                    },
                )

                self.logger.error(
                    "Vector operation failed",
                    operation=operation,
                    correlation_id=context.correlation_id,
                    error=str(e),
                    exc_info=True,
                )

                return PluginResult(
                    correlation_id=context.correlation_id,
                    success=False,
                    error_message=str(e),
                    execution_time_ms=execution_time,
                    metadata={"operation": operation, "error_type": type(e).__name__},
                )

    async def _handle_semantic_search(
        self, context: PluginContext, span: trace.Span
    ) -> list[dict[str, Any]]:
        query = context.execution_context.get("query", "")
        limit = context.execution_context.get("limit", 10)
        threshold = context.execution_context.get("threshold", 0.7)

        if not query:
            raise ValueError("Query is required for semantic search")

        span.set_attributes(
            {
                "search.query_length": len(query),
                "search.limit": limit,
                "search.threshold": threshold,
            }
        )

        from app.core.vector.semantic.matcher import SemanticMatchRequest

        if not self.semantic_matcher:
            raise ValueError("Semantic matcher not initialized")

        match_request = SemanticMatchRequest(
            resource_type="deployment",
            requirements={},
            query_text=query,
            threshold=threshold,
            max_results=limit,
            include_metadata=True,
        )

        match_response = await self.semantic_matcher.find_similar_resources(match_request)
        results = [
            {
                "id": match.resource_id,
                "score": match.similarity_score,
                "summary": match.matched_content,
                "metadata": match.metadata,
            }
            for match in match_response.matches
        ]

        span.set_attribute("search.results_count", len(results))

        self.logger.info(
            "Semantic search completed",
            query=query[:100],
            results_count=len(results),
            correlation_id=context.correlation_id,
        )

        return results

    async def _handle_resource_indexing(
        self, context: PluginContext, span: trace.Span
    ) -> dict[str, Any]:
        resource_data = context.execution_context.get("resource_data")
        resource_type = context.execution_context.get("resource_type", "unknown")
        resource_id = context.execution_context.get("resource_id")

        if not resource_data:
            raise ValueError("Resource data is required for indexing")

        span.set_attributes(
            {
                "indexing.resource_type": resource_type,
                "indexing.resource_id": resource_id or "auto_generated",
                "indexing.data_size": len(str(resource_data)),
            }
        )

        from app.core.schemas.domains.resources import AzureResource
        from app.core.vector.semantic.indexer import ResourceIndexRequest

        # Extract deployment context from resource data
        if isinstance(resource_data, dict):
            deployment_context = resource_data.get("deployment_context", {})
            resource_group = deployment_context.get("resource_group") or resource_data.get(
                "resource_group"
            )
            location = deployment_context.get("location") or resource_data.get("location")
        else:
            deployment_context = {}
            resource_group = None
            location = None

        # Fallback to context if not in resource data
        resource_group = (
            resource_group
            or context.execution_context.get("resource_group")
            or context.user_context.get("resource_group", "unknown-rg")
        )
        location = (
            location
            or context.execution_context.get("location")
            or context.user_context.get("location", "westeurope")
        )

        # Create an AzureResource from the data
        azure_resource = AzureResource(
            resource_id=resource_id or f"auto_{hash(str(resource_data))}",
            resource_type=resource_type,
            resource_name=f"{resource_type}_{resource_id or 'unnamed'}",
            properties=(
                resource_data if isinstance(resource_data, dict) else {"data": resource_data}
            ),
        )
        # Set mixin fields separately
        azure_resource.resource_group = resource_group
        azure_resource.location = location

        if not self.resource_indexer:
            raise ValueError("Resource indexer not initialized")

        index_request = ResourceIndexRequest(resource=azure_resource, force_reindex=True)

        index_result = await self.resource_indexer.index_resource(index_request)
        indexed_id = index_result.resource_id

        span.set_attribute("indexing.indexed_id", indexed_id)

        self.logger.info(
            "Resource indexed",
            resource_type=resource_type,
            indexed_id=indexed_id,
            correlation_id=context.correlation_id,
        )

        return {"indexed_id": indexed_id, "resource_type": resource_type, "status": "indexed"}

    async def _handle_similarity_search(
        self, context: PluginContext, span: trace.Span
    ) -> list[dict[str, Any]]:
        embedding = context.execution_context.get("embedding")
        text = context.execution_context.get("text")
        limit = context.execution_context.get("limit", 10)

        if not embedding and not text:
            raise ValueError("Either embedding or text is required for similarity search")

        if text and not embedding:
            cache_key = f"embed_{hash(text)}"
            if cache_key in self._embedding_cache:
                cache_time = self._cache_timestamps.get(cache_key)
                ttl_hours = self.config.configuration.get("cache_ttl_hours", 24)
                if cache_time and (datetime.now(UTC) - cache_time) < timedelta(hours=ttl_hours):
                    embedding = self._embedding_cache[cache_key]
                    span.set_attribute("embedding.from_cache", True)

            if not embedding:
                if not self.semantic_matcher:
                    raise ValueError("Semantic matcher not initialized")
                embedding = await self.semantic_matcher.get_embedding(text)
                self._embedding_cache[cache_key] = embedding
                self._cache_timestamps[cache_key] = datetime.now(UTC)
                span.set_attribute("embedding.from_cache", False)

        span.set_attributes(
            {
                "similarity.has_embedding": bool(embedding),
                "similarity.limit": limit,
                "similarity.embedding_dim": len(embedding) if embedding else 0,
            }
        )

        if not self.vector_registry:
            raise ValueError("Vector registry not initialized")

        if not embedding or not isinstance(embedding, list):
            raise ValueError("Valid embedding is required for similarity search")

        results = await self.vector_registry.similarity_search(embedding=embedding, limit=limit)

        span.set_attribute("similarity.results_count", len(results))

        return results

    async def _handle_context_retrieval(
        self, context: PluginContext, span: trace.Span
    ) -> dict[str, Any]:
        user_id = context.user_context.get("user_id")
        query = context.execution_context.get("query")
        context_types = context.execution_context.get(
            "context_types", ["deployment", "conversation"]
        )

        if not user_id or not query:
            raise ValueError("user_id and query are required for context retrieval")

        span.set_attributes(
            {
                "context.user_id": user_id,
                "context.query_length": len(query),
                "context.types": context_types,
            }
        )

        memory = await get_agent_memory()

        relevant_contexts = []
        search_results = await self._handle_semantic_search(
            PluginContext(
                plugin_name=self.metadata.name,
                correlation_id=context.correlation_id,
                execution_context={
                    "operation": "semantic_search",
                    "query": query,
                    "limit": 5,
                    "threshold": 0.6,
                },
            ),
            span,
        )

        for result in search_results:
            if result.get("metadata", {}).get("user_id") == user_id:
                relevant_contexts.append(result)

        stored_contexts = await memory.list_contexts(user_id)

        span.set_attributes(
            {
                "context.search_results": len(search_results),
                "context.relevant_results": len(relevant_contexts),
                "context.stored_contexts": len(stored_contexts),
            }
        )

        return {
            "semantic_matches": relevant_contexts,
            "stored_contexts": stored_contexts[:5],
            "query": query,
            "total_matches": len(relevant_contexts),
        }

    async def _handle_cleanup(self, context: PluginContext, span: trace.Span) -> dict[str, Any]:
        max_age_days = context.execution_context.get("max_age_days", 30)

        span.set_attribute("cleanup.max_age_days", max_age_days)

        if not self.vector_registry:
            raise ValueError("Vector registry not initialized")

        cleaned_vectors = await self.vector_registry.cleanup_old_vectors(
            max_age=timedelta(days=max_age_days)
        )

        cache_cleaned = len(self._embedding_cache)
        self._embedding_cache.clear()
        self._cache_timestamps.clear()

        memory = await get_agent_memory()
        cleaned_memory = await memory.cleanup_expired()

        span.set_attributes(
            {
                "cleanup.vectors_cleaned": cleaned_vectors,
                "cleanup.cache_cleaned": cache_cleaned,
                "cleanup.memory_cleaned": cleaned_memory,
            }
        )

        self.logger.info(
            "Cleanup completed",
            vectors_cleaned=cleaned_vectors,
            cache_cleaned=cache_cleaned,
            memory_cleaned=cleaned_memory,
        )

        return {
            "vectors_cleaned": cleaned_vectors,
            "cache_cleaned": cache_cleaned,
            "memory_cleaned": cleaned_memory,
            "total_cleaned": cleaned_vectors + cache_cleaned + cleaned_memory,
        }

    async def shutdown(self) -> None:
        with tracer.start_as_current_span("vector_plugin_shutdown") as span:
            try:
                if self.vector_registry:
                    await self.vector_registry.shutdown()

                if self.semantic_matcher:
                    await self.semantic_matcher.shutdown()

                if self.resource_indexer:
                    await self.resource_indexer.shutdown()

                self._embedding_cache.clear()
                self._cache_timestamps.clear()

                span.set_status(Status(StatusCode.OK))
                self.logger.info("Vector database plugin shut down")

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error(
                    "Error during vector plugin shutdown", error=str(e), exc_info=True
                )
                raise
