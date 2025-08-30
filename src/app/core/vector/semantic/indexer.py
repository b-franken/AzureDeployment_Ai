from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, UTC
from enum import Enum

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.schemas.base import BaseSchema
from app.core.schemas.domains.resources import AzureResource
from ..providers.base import VectorProvider

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)


class IndexStatus(str, Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


class ResourceIndexRequest(BaseSchema):
    resource: AzureResource = Field(description="Azure resource to index")
    content_override: Optional[str] = Field(default=None, description="Custom content for indexing")
    embedding_override: Optional[List[float]] = Field(default=None, description="Pre-computed embedding")
    force_reindex: bool = Field(default=False, description="Force reindex if already exists")


class ResourceIndexResult(BaseSchema):
    resource_id: str = Field(description="Indexed resource identifier")
    resource_type: str = Field(description="Type of indexed resource")
    index_status: IndexStatus = Field(description="Indexing status")
    content: str = Field(description="Content that was indexed")
    embedding_dimension: int = Field(description="Dimension of generated embedding")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Indexed metadata")
    indexing_time_ms: float = Field(description="Time taken to index")
    error_message: Optional[str] = Field(default=None, description="Error if indexing failed")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BulkIndexRequest(BaseSchema):
    resources: List[ResourceIndexRequest] = Field(description="List of resources to index")
    batch_size: int = Field(default=50, ge=1, le=1000, description="Processing batch size")
    continue_on_error: bool = Field(default=True, description="Continue processing on individual errors")


class BulkIndexResponse(BaseSchema):
    total_resources: int = Field(description="Total resources requested for indexing")
    successful_indexes: int = Field(description="Number of successfully indexed resources")
    failed_indexes: int = Field(description="Number of failed indexes")
    results: List[ResourceIndexResult] = Field(description="Individual indexing results")
    total_time_ms: float = Field(description="Total processing time")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResourceIndexer:
    def __init__(self, 
                 vector_provider: VectorProvider, 
                 collection_name: str = "azure_resources",
                 embedding_dimension: int = 1536):
        self.vector_provider = vector_provider
        self.collection_name = collection_name
        self.embedding_dimension = embedding_dimension
        self.logger = logger.bind(component="resource_indexer")
    
    async def ensure_collection_exists(self) -> bool:
        with tracer.start_as_current_span("ensure_collection") as span:
            span.set_attributes({
                "collection.name": self.collection_name,
                "collection.dimension": self.embedding_dimension
            })
            
            try:
                collections = await self.vector_provider.list_collections()
                
                if self.collection_name not in collections:
                    self.logger.info(
                        "creating_vector_collection",
                        collection=self.collection_name,
                        dimension=self.embedding_dimension
                    )
                    
                    success = await self.vector_provider.create_collection(
                        collection_name=self.collection_name,
                        dimension=self.embedding_dimension,
                        metadata={
                            "purpose": "azure_resource_indexing",
                            "created_at": datetime.now(UTC).isoformat(),
                            "dimension": self.embedding_dimension
                        }
                    )
                    
                    if success:
                        span.set_status(Status(StatusCode.OK))
                        self.logger.info("collection_created", collection=self.collection_name)
                        return True
                    else:
                        span.set_status(Status(StatusCode.ERROR, "Failed to create collection"))
                        self.logger.error("collection_creation_failed", collection=self.collection_name)
                        return False
                else:
                    span.set_status(Status(StatusCode.OK))
                    return True
                    
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error(
                    "collection_check_failed",
                    collection=self.collection_name,
                    error=str(e),
                    exc_info=True
                )
                return False
    
    async def index_resource(self, request: ResourceIndexRequest) -> ResourceIndexResult:
        with tracer.start_as_current_span("index_single_resource") as span:
            resource = request.resource
            span.set_attributes({
                "resource.id": resource.resource_id,
                "resource.type": resource.resource_type,
                "resource.name": resource.resource_name,
                "indexing.force_reindex": request.force_reindex
            })
            
            start_time = datetime.now(UTC)
            
            try:
                await self.ensure_collection_exists()
                
                content = request.content_override or self._generate_content(resource)
                
                existing_vector = await self.vector_provider.get_vector_by_id(
                    collection_name=self.collection_name,
                    vector_id=resource.resource_id
                )
                
                if existing_vector and not request.force_reindex:
                    execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                    
                    result = ResourceIndexResult(
                        resource_id=resource.resource_id,
                        resource_type=resource.resource_type,
                        index_status=IndexStatus.COMPLETED,
                        content=content,
                        embedding_dimension=len(existing_vector.embedding or []),
                        metadata=existing_vector.metadata,
                        indexing_time_ms=execution_time,
                    )
                    
                    span.set_status(Status(StatusCode.OK))
                    self.logger.info(
                        "resource_already_indexed",
                        resource_id=resource.resource_id,
                        resource_type=resource.resource_type
                    )
                    
                    return result
                
                embedding = request.embedding_override or await self._generate_embedding(content)
                
                metadata = {
                    "resource_id": resource.resource_id,
                    "resource_type": resource.resource_type,
                    "resource_name": resource.resource_name,
                    "resource_group": getattr(resource, "resource_group", None),
                    "location": getattr(resource, "location", None),
                    "environment": getattr(resource, "environment", None),
                    "tags": getattr(resource, "tags", {}),
                    "sku": resource.sku,
                    "status": resource.status,
                    "indexed_at": datetime.now(UTC).isoformat(),
                    "content_length": len(content),
                    "embedding_dimension": len(embedding)
                }
                
                vector_data = [{
                    "id": resource.resource_id,
                    "values": embedding,
                    "metadata": metadata
                }]
                
                success = await self.vector_provider.upsert_vectors(
                    collection_name=self.collection_name,
                    vectors=vector_data
                )
                
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                if success:
                    result = ResourceIndexResult(
                        resource_id=resource.resource_id,
                        resource_type=resource.resource_type,
                        index_status=IndexStatus.COMPLETED,
                        content=content,
                        embedding_dimension=len(embedding),
                        metadata=metadata,
                        indexing_time_ms=execution_time,
                    )
                    
                    span.set_attributes({
                        "indexing.success": True,
                        "indexing.content_length": len(content),
                        "indexing.embedding_dimension": len(embedding),
                        "indexing.execution_time_ms": execution_time
                    })
                    span.set_status(Status(StatusCode.OK))
                    
                    self.logger.info(
                        "resource_indexed_successfully",
                        resource_id=resource.resource_id,
                        resource_type=resource.resource_type,
                        execution_time_ms=execution_time
                    )
                    
                    return result
                else:
                    raise Exception("Vector upsert failed")
                    
            except Exception as e:
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                self.logger.error(
                    "resource_indexing_failed",
                    resource_id=resource.resource_id,
                    resource_type=resource.resource_type,
                    error=str(e),
                    execution_time_ms=execution_time,
                    exc_info=True
                )
                
                return ResourceIndexResult(
                    resource_id=resource.resource_id,
                    resource_type=resource.resource_type,
                    index_status=IndexStatus.FAILED,
                    content=content if 'content' in locals() else "",
                    embedding_dimension=0,
                    metadata={},
                    indexing_time_ms=execution_time,
                    error_message=str(e)
                )
    
    async def bulk_index(self, request: BulkIndexRequest) -> BulkIndexResponse:
        with tracer.start_as_current_span("bulk_resource_indexing") as span:
            span.set_attributes({
                "bulk.total_resources": len(request.resources),
                "bulk.batch_size": request.batch_size,
                "bulk.continue_on_error": request.continue_on_error
            })
            
            start_time = datetime.now(UTC)
            results: List[ResourceIndexResult] = []
            successful_count = 0
            failed_count = 0
            
            try:
                await self.ensure_collection_exists()
                
                for i in range(0, len(request.resources), request.batch_size):
                    batch = request.resources[i:i + request.batch_size]
                    
                    for resource_request in batch:
                        try:
                            result = await self.index_resource(resource_request)
                            results.append(result)
                            
                            if result.index_status == IndexStatus.COMPLETED:
                                successful_count += 1
                            else:
                                failed_count += 1
                                
                        except Exception as e:
                            failed_count += 1
                            
                            error_result = ResourceIndexResult(
                                resource_id=resource_request.resource.resource_id,
                                resource_type=resource_request.resource.resource_type,
                                index_status=IndexStatus.FAILED,
                                content="",
                                embedding_dimension=0,
                                metadata={},
                                indexing_time_ms=0,
                                error_message=str(e)
                            )
                            results.append(error_result)
                            
                            if not request.continue_on_error:
                                break
                
                total_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                response = BulkIndexResponse(
                    total_resources=len(request.resources),
                    successful_indexes=successful_count,
                    failed_indexes=failed_count,
                    results=results,
                    total_time_ms=total_time
                )
                
                span.set_attributes({
                    "bulk.successful": successful_count,
                    "bulk.failed": failed_count,
                    "bulk.total_time_ms": total_time
                })
                span.set_status(Status(StatusCode.OK))
                
                self.logger.info(
                    "bulk_indexing_completed",
                    total_resources=len(request.resources),
                    successful=successful_count,
                    failed=failed_count,
                    total_time_ms=total_time
                )
                
                return response
                
            except Exception as e:
                total_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                self.logger.error(
                    "bulk_indexing_failed",
                    total_resources=len(request.resources),
                    error=str(e),
                    total_time_ms=total_time,
                    exc_info=True
                )
                
                return BulkIndexResponse(
                    total_resources=len(request.resources),
                    successful_indexes=successful_count,
                    failed_indexes=failed_count,
                    results=results,
                    total_time_ms=total_time
                )
    
    async def delete_resource_index(self, resource_id: str) -> bool:
        with tracer.start_as_current_span("delete_resource_index") as span:
            span.set_attribute("resource.id", resource_id)
            
            try:
                success = await self.vector_provider.delete_vectors(
                    collection_name=self.collection_name,
                    vector_ids=[resource_id]
                )
                
                span.set_attributes({
                    "deletion.success": success,
                    "collection.name": self.collection_name
                })
                
                if success:
                    span.set_status(Status(StatusCode.OK))
                    self.logger.info(
                        "resource_index_deleted",
                        resource_id=resource_id,
                        collection=self.collection_name
                    )
                else:
                    span.set_status(Status(StatusCode.ERROR, "Deletion failed"))
                    self.logger.error(
                        "resource_index_deletion_failed",
                        resource_id=resource_id,
                        collection=self.collection_name
                    )
                
                return success
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                self.logger.error(
                    "resource_index_deletion_error",
                    resource_id=resource_id,
                    collection=self.collection_name,
                    error=str(e),
                    exc_info=True
                )
                
                return False
    
    def _generate_content(self, resource: AzureResource) -> str:
        content_parts = [
            f"Resource Type: {resource.resource_type}",
            f"Resource Name: {resource.resource_name}",
            f"Status: {resource.status}"
        ]
        
        if resource.sku:
            content_parts.append(f"SKU: {resource.sku}")
        
        if hasattr(resource, "location"):
            content_parts.append(f"Location: {resource.location}")
        
        if hasattr(resource, "environment"):
            content_parts.append(f"Environment: {resource.environment}")
        
        if hasattr(resource, "tags") and resource.tags:
            tags_str = ", ".join(f"{k}:{v}" for k, v in resource.tags.items())
            content_parts.append(f"Tags: {tags_str}")
        
        if resource.properties:
            props_str = ", ".join(f"{k}:{v}" for k, v in resource.properties.items())
            content_parts.append(f"Properties: {props_str}")
        
        return "\n".join(content_parts)
    
    async def _generate_embedding(self, content: str) -> List[float]:
        # Placeholder for embedding generation
        # In a real implementation, this would call an embedding service
        # like OpenAI, Azure Cognitive Services, or a local model
        import hashlib
        import struct
        
        hash_bytes = hashlib.sha256(content.encode()).digest()
        embedding = []
        
        for i in range(0, min(len(hash_bytes), self.embedding_dimension * 4), 4):
            chunk = hash_bytes[i:i+4]
            if len(chunk) == 4:
                value = struct.unpack('f', chunk)[0]
                embedding.append(float(value))
        
        while len(embedding) < self.embedding_dimension:
            embedding.append(0.0)
        
        return embedding[:self.embedding_dimension]
    
    async def get_indexer_stats(self) -> Dict[str, Any]:
        with tracer.start_as_current_span("indexer_stats") as span:
            try:
                provider_stats = await self.vector_provider.get_stats(self.collection_name)
                
                stats = {
                    "indexer_name": "ResourceIndexer",
                    "collection_name": self.collection_name,
                    "embedding_dimension": self.embedding_dimension,
                    "provider": self.vector_provider.name,
                    "provider_stats": provider_stats,
                    "timestamp": datetime.now(UTC).isoformat()
                }
                
                span.set_status(Status(StatusCode.OK))
                return stats
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                return {
                    "indexer_name": "ResourceIndexer",
                    "collection_name": self.collection_name,
                    "embedding_dimension": self.embedding_dimension,
                    "provider": self.vector_provider.name,
                    "error": str(e),
                    "timestamp": datetime.now(UTC).isoformat()
                }