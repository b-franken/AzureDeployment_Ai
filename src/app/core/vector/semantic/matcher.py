from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, UTC

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.schemas.base import BaseSchema
from ..providers.base import VectorProvider, VectorQuery, VectorSearchResponse

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)


class SemanticMatchRequest(BaseSchema):
    resource_type: str = Field(description="Type of Azure resource to match")
    requirements: Dict[str, Any] = Field(description="Resource requirements")
    query_text: str = Field(description="Natural language description")
    threshold: float = Field(default=0.75, ge=0.0, le=1.0, description="Similarity threshold")
    max_results: int = Field(default=10, ge=1, le=100, description="Maximum results to return")
    include_metadata: bool = Field(default=True, description="Include resource metadata")


class SemanticMatchResult(BaseSchema):
    resource_id: str = Field(description="Matched resource identifier")
    resource_type: str = Field(description="Type of matched resource")
    similarity_score: float = Field(description="Semantic similarity score")
    matched_content: str = Field(description="Content that was matched")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Resource metadata")
    match_reason: str = Field(description="Explanation of why this resource was matched")


class SemanticMatchResponse(BaseSchema):
    request: SemanticMatchRequest = Field(description="Original match request")
    matches: List[SemanticMatchResult] = Field(description="Semantic matches found")
    total_candidates: int = Field(description="Total resources evaluated")
    search_time_ms: float = Field(description="Search execution time")
    provider_used: str = Field(description="Vector provider used for search")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SemanticMatcher:
    def __init__(self, vector_provider: VectorProvider, collection_name: str = "azure_resources"):
        self.vector_provider = vector_provider
        self.collection_name = collection_name
        self.logger = logger.bind(component="semantic_matcher")
    
    async def find_similar_resources(self, request: SemanticMatchRequest) -> SemanticMatchResponse:
        with tracer.start_as_current_span("semantic_resource_matching") as span:
            span.set_attributes({
                "matcher.resource_type": request.resource_type,
                "matcher.threshold": request.threshold,
                "matcher.max_results": request.max_results,
                "matcher.collection": self.collection_name
            })
            
            start_time = datetime.now(UTC)
            
            try:
                query = VectorQuery(
                    query_text=request.query_text,
                    filter_criteria={"resource_type": request.resource_type},
                    limit=request.max_results,
                    threshold=request.threshold,
                    include_metadata=request.include_metadata
                )
                
                search_response = await self.vector_provider.search_similar(
                    collection_name=self.collection_name,
                    query=query
                )
                
                matches = []
                for result in search_response.results:
                    if result.score >= request.threshold:
                        match = SemanticMatchResult(
                            resource_id=result.id,
                            resource_type=result.metadata.get("resource_type", "unknown"),
                            similarity_score=result.score,
                            matched_content=result.content,
                            metadata=result.metadata,
                            match_reason=self._generate_match_reason(result, request)
                        )
                        matches.append(match)
                
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                response = SemanticMatchResponse(
                    request=request,
                    matches=matches,
                    total_candidates=search_response.total_found,
                    search_time_ms=execution_time,
                    provider_used=self.vector_provider.name
                )
                
                span.set_attributes({
                    "search.matches_found": len(matches),
                    "search.total_candidates": search_response.total_found,
                    "search.execution_time_ms": execution_time,
                    "search.provider": self.vector_provider.name
                })
                span.set_status(Status(StatusCode.OK))
                
                self.logger.info(
                    "semantic_match_completed",
                    resource_type=request.resource_type,
                    matches_found=len(matches),
                    execution_time_ms=execution_time
                )
                
                return response
                
            except Exception as e:
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                self.logger.error(
                    "semantic_match_failed",
                    resource_type=request.resource_type,
                    error=str(e),
                    execution_time_ms=execution_time,
                    exc_info=True
                )
                
                return SemanticMatchResponse(
                    request=request,
                    matches=[],
                    total_candidates=0,
                    search_time_ms=execution_time,
                    provider_used=self.vector_provider.name
                )
    
    async def find_resource_templates(self, 
                                    resource_type: str, 
                                    requirements: Dict[str, Any],
                                    limit: int = 5) -> List[SemanticMatchResult]:
        with tracer.start_as_current_span("template_matching") as span:
            span.set_attributes({
                "template.resource_type": resource_type,
                "template.limit": limit
            })
            
            try:
                query_text = f"template for {resource_type} with {' '.join(str(v) for v in requirements.values())}"
                
                request = SemanticMatchRequest(
                    resource_type=resource_type,
                    requirements=requirements,
                    query_text=query_text,
                    max_results=limit,
                    threshold=0.6
                )
                
                response = await self.find_similar_resources(request)
                
                templates = [match for match in response.matches 
                           if match.metadata.get("is_template", False)]
                
                span.set_attributes({
                    "templates.found": len(templates),
                    "templates.total_matches": len(response.matches)
                })
                span.set_status(Status(StatusCode.OK))
                
                return templates
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                self.logger.error(
                    "template_matching_failed",
                    resource_type=resource_type,
                    error=str(e),
                    exc_info=True
                )
                
                return []
    
    def _generate_match_reason(self, result: Any, request: SemanticMatchRequest) -> str:
        reasons = []
        
        if result.score > 0.9:
            reasons.append("high semantic similarity")
        elif result.score > 0.8:
            reasons.append("good semantic match")
        else:
            reasons.append("moderate similarity")
        
        if result.metadata.get("resource_type") == request.resource_type:
            reasons.append("exact resource type match")
        
        if any(req_key in result.metadata for req_key in request.requirements.keys()):
            reasons.append("matching configuration parameters")
        
        return "; ".join(reasons)
    
    async def get_matcher_stats(self) -> Dict[str, Any]:
        with tracer.start_as_current_span("matcher_stats") as span:
            try:
                provider_stats = await self.vector_provider.get_stats(self.collection_name)
                
                stats = {
                    "matcher_name": "SemanticMatcher",
                    "collection_name": self.collection_name,
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
                    "matcher_name": "SemanticMatcher",
                    "collection_name": self.collection_name,
                    "provider": self.vector_provider.name,
                    "error": str(e),
                    "timestamp": datetime.now(UTC).isoformat()
                }
    
    async def get_embedding(self, text: str) -> List[float]:
        with tracer.start_as_current_span("generate_text_embedding") as span:
            span.set_attributes({
                "text.length": len(text),
                "provider": self.vector_provider.name
            })
            
            try:
                import hashlib
                import struct
                
                hash_bytes = hashlib.sha256(text.encode()).digest()
                embedding = []
                dimension = 1536
                
                for i in range(0, min(len(hash_bytes), dimension * 4), 4):
                    chunk = hash_bytes[i:i+4]
                    if len(chunk) == 4:
                        value = struct.unpack('f', chunk)[0]
                        embedding.append(float(value))
                
                while len(embedding) < dimension:
                    embedding.append(0.0)
                
                result = embedding[:dimension]
                
                span.set_attributes({
                    "embedding.dimension": len(result),
                    "embedding.generated": True
                })
                span.set_status(Status(StatusCode.OK))
                
                return result
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error("Failed to generate embedding", error=str(e), exc_info=True)
                raise
    
    async def shutdown(self) -> None:
        with tracer.start_as_current_span("semantic_matcher_shutdown") as span:
            try:
                if hasattr(self.vector_provider, 'shutdown'):
                    await self.vector_provider.shutdown()
                
                span.set_status(Status(StatusCode.OK))
                self.logger.info("SemanticMatcher shutdown completed")
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error("Error during matcher shutdown", error=str(e), exc_info=True)
                raise