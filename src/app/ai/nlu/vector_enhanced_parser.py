from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, UTC

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .unified_parser import UnifiedParseResult, parse_provision_request
from app.core.plugins.manager import PluginManager
from app.core.plugins.base import PluginContext
from app.observability.app_insights import app_insights
from app.observability.distributed_tracing import get_service_tracer
from app.core.logging import get_logger

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)


class VectorEnhancedParser:
    def __init__(self, plugin_manager: PluginManager):
        self.plugin_manager = plugin_manager
        self.service_tracer = get_service_tracer("vector_enhanced_parser")
        self.logger = logger.bind(component="vector_nlu")
        
        self._vector_plugin_name = "vector_database"
        self._context_cache: Dict[str, Any] = {}
    
    async def parse_with_context(
        self,
        request_text: str,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        include_similar_requests: bool = True,
        similarity_threshold: float = 0.7
    ) -> Dict[str, Any]:
        async with self.service_tracer.start_distributed_span(
            operation_name="vector_enhanced_parsing",
            correlation_id=correlation_id,
            user_id=user_id,
            attributes={
                "parser.request_length": len(request_text),
                "parser.include_similar": include_similar_requests,
                "parser.threshold": similarity_threshold
            }
        ) as span:
            start_time = datetime.now(UTC)
            
            try:
                base_parse_result = parse_provision_request(request_text)
                
                enhanced_result = {
                    "base_parse": base_parse_result.dict(),
                    "vector_enhanced": True,
                    "parsing_timestamp": datetime.now(UTC).isoformat(),
                    "similar_requests": [],
                    "context_suggestions": [],
                    "confidence_boost": 0.0,
                    "enhanced_parameters": {}
                }
                
                if include_similar_requests:
                    similar_context = await self._get_similar_requests(
                        request_text, user_id, correlation_id, similarity_threshold, span
                    )
                    
                    enhanced_result["similar_requests"] = similar_context.get("similar_requests", [])
                    enhanced_result["context_suggestions"] = similar_context.get("suggestions", [])
                    
                    enhanced_parameters = await self._enhance_parameters_from_context(
                        base_parse_result, similar_context, span
                    )
                    enhanced_result["enhanced_parameters"] = enhanced_parameters
                    
                    confidence_boost = self._calculate_confidence_boost(similar_context)
                    enhanced_result["confidence_boost"] = confidence_boost
                
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                span.set_attributes({
                    "parser.execution_time_ms": execution_time,
                    "parser.similar_requests_found": len(enhanced_result["similar_requests"]),
                    "parser.confidence_boost": enhanced_result["confidence_boost"],
                    "parser.base_confidence": base_parse_result.confidence
                })
                
                app_insights.track_custom_event(
                    "vector_enhanced_parsing_completed",
                    {
                        "user_id": user_id or "anonymous",
                        "correlation_id": correlation_id or "none",
                        "resource_type": base_parse_result.resource_type or "unknown"
                    },
                    {
                        "execution_time_ms": execution_time,
                        "similar_requests_found": len(enhanced_result["similar_requests"]),
                        "confidence_boost": enhanced_result["confidence_boost"]
                    }
                )
                
                span.set_status(Status(StatusCode.OK))
                return enhanced_result
                
            except Exception as e:
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                app_insights.track_exception(
                    e,
                    {
                        "user_id": user_id or "anonymous",
                        "correlation_id": correlation_id or "none",
                        "operation": "vector_enhanced_parsing"
                    }
                )
                
                self.logger.error(
                    "Vector-enhanced parsing failed",
                    user_id=user_id,
                    correlation_id=correlation_id,
                    error=str(e),
                    exc_info=True
                )
                
                return {
                    "base_parse": parse_provision_request(request_text).dict(),
                    "vector_enhanced": False,
                    "parsing_timestamp": datetime.now(UTC).isoformat(),
                    "similar_requests": [],
                    "context_suggestions": [],
                    "confidence_boost": 0.0,
                    "enhanced_parameters": {},
                    "error": str(e)
                }
    
    async def _get_similar_requests(
        self,
        request_text: str,
        user_id: Optional[str],
        correlation_id: Optional[str],
        threshold: float,
        span
    ) -> Dict[str, Any]:
        with tracer.start_as_current_span("get_similar_requests") as similar_span:
            cache_key = f"{user_id}:{hash(request_text)}:{threshold}"
            if cache_key in self._context_cache:
                similar_span.set_attribute("context.from_cache", True)
                return self._context_cache[cache_key]
            
            try:
                plugin_context = PluginContext(
                    plugin_name=self._vector_plugin_name,
                    correlation_id=correlation_id or "parser_similarity_search",
                    execution_context={
                        "operation": "semantic_search",
                        "query": request_text,
                        "limit": 10,
                        "threshold": threshold
                    },
                    user_context={
                        "user_id": user_id
                    } if user_id else {}
                )
                
                plugin_result = await self.plugin_manager.execute_plugin(
                    self._vector_plugin_name,
                    plugin_context
                )
                
                similar_context = {
                    "similar_requests": [],
                    "suggestions": [],
                    "patterns": {}
                }
                
                if plugin_result.success:
                    similar_requests = plugin_result.result
                    similar_context["similar_requests"] = similar_requests
                    
                    resource_patterns = {}
                    success_patterns = []
                    
                    for req in similar_requests:
                        metadata = req.get("metadata", {})
                        resource_type = metadata.get("resource_type", "unknown")
                        
                        if resource_type not in resource_patterns:
                            resource_patterns[resource_type] = {"count": 0, "success_rate": 0, "configurations": []}
                        
                        resource_patterns[resource_type]["count"] += 1
                        
                        if metadata.get("success"):
                            success_patterns.append({
                                "resource_type": resource_type,
                                "configuration": req.get("summary", "")[:200],
                                "similarity_score": req.get("score", 0.0)
                            })
                    
                    similar_context["patterns"] = resource_patterns
                    
                    suggestions = []
                    if success_patterns:
                        most_similar = max(success_patterns, key=lambda x: x["similarity_score"])
                        suggestions.append(f"Consider pattern from successful {most_similar['resource_type']} deployment")
                    
                    if resource_patterns:
                        most_common = max(resource_patterns.items(), key=lambda x: x[1]["count"])
                        suggestions.append(f"Most commonly deployed: {most_common[0]}")
                    
                    similar_context["suggestions"] = suggestions
                    
                    self._context_cache[cache_key] = similar_context
                    
                    similar_span.set_attributes({
                        "similar.requests_found": len(similar_requests),
                        "similar.patterns_found": len(resource_patterns),
                        "similar.suggestions_generated": len(suggestions)
                    })
                else:
                    similar_span.set_attribute("similar.plugin_error", plugin_result.error_message)
                    self.logger.warning("Failed to get similar requests", error=plugin_result.error_message)
                
                return similar_context
                
            except Exception as e:
                similar_span.record_exception(e)
                self.logger.error("Error getting similar requests", error=str(e), exc_info=True)
                return {"similar_requests": [], "suggestions": [], "patterns": {}}
    
    async def _enhance_parameters_from_context(
        self,
        base_result: UnifiedParseResult,
        similar_context: Dict[str, Any],
        span
    ) -> Dict[str, Any]:
        with tracer.start_as_current_span("enhance_parameters") as param_span:
            enhanced_params = {}
            similar_requests = similar_context.get("similar_requests", [])
            
            if not similar_requests:
                param_span.set_attribute("enhancement.no_similar_requests", True)
                return enhanced_params
            
            resource_type = base_result.resource_type
            if not resource_type:
                param_span.set_attribute("enhancement.no_resource_type", True)
                return enhanced_params
            
            matching_resources = [
                req for req in similar_requests 
                if req.get("metadata", {}).get("resource_type") == resource_type
            ]
            
            if not matching_resources:
                param_span.set_attribute("enhancement.no_matching_resources", True)
                return enhanced_params
            
            successful_resources = [
                req for req in matching_resources 
                if req.get("metadata", {}).get("success", False)
            ]
            
            if successful_resources:
                best_match = max(successful_resources, key=lambda x: x.get("score", 0.0))
                best_metadata = best_match.get("metadata", {})
                
                if "location" not in (base_result.parameters or {}) and best_metadata.get("location"):
                    enhanced_params["suggested_location"] = best_metadata["location"]
                
                if "environment" not in (base_result.parameters or {}) and best_metadata.get("environment"):
                    enhanced_params["suggested_environment"] = best_metadata["environment"]
                
                if best_metadata.get("tags"):
                    enhanced_params["suggested_tags"] = best_metadata["tags"]
                
                if best_metadata.get("resource_configuration"):
                    enhanced_params["recommended_configuration"] = best_metadata["resource_configuration"]
                
                enhanced_params["confidence_source"] = f"Based on similar successful {resource_type} deployment"
                enhanced_params["similarity_score"] = best_match.get("score", 0.0)
            
            param_span.set_attributes({
                "enhancement.matching_resources": len(matching_resources),
                "enhancement.successful_resources": len(successful_resources),
                "enhancement.parameters_enhanced": len(enhanced_params)
            })
            
            return enhanced_params
    
    def _calculate_confidence_boost(self, similar_context: Dict[str, Any]) -> float:
        similar_requests = similar_context.get("similar_requests", [])
        
        if not similar_requests:
            return 0.0
        
        high_similarity_count = len([
            req for req in similar_requests 
            if req.get("score", 0.0) > 0.8
        ])
        
        successful_count = len([
            req for req in similar_requests 
            if req.get("metadata", {}).get("success", False)
        ])
        
        confidence_boost = 0.0
        
        if high_similarity_count > 0:
            confidence_boost += min(0.2, high_similarity_count * 0.05)
        
        if successful_count > 0:
            success_rate = successful_count / len(similar_requests)
            confidence_boost += success_rate * 0.15
        
        return min(0.3, confidence_boost)
    
    async def get_parsing_recommendations(
        self,
        request_text: str,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        async with self.service_tracer.start_distributed_span(
            operation_name="get_parsing_recommendations",
            correlation_id=f"rec_{user_id}_{hash(request_text)}",
            user_id=user_id,
            attributes={
                "recommendations.request_length": len(request_text)
            }
        ) as span:
            try:
                enhanced_parse = await self.parse_with_context(
                    request_text=request_text,
                    user_id=user_id,
                    correlation_id=f"rec_{user_id}_{hash(request_text)}",
                    include_similar_requests=True,
                    similarity_threshold=0.6
                )
                
                recommendations = {
                    "request": request_text,
                    "parsing_confidence": enhanced_parse["base_parse"]["confidence"],
                    "vector_confidence_boost": enhanced_parse["confidence_boost"],
                    "total_confidence": min(1.0, enhanced_parse["base_parse"]["confidence"] + enhanced_parse["confidence_boost"]),
                    "recommendations": enhanced_parse["context_suggestions"],
                    "similar_patterns": len(enhanced_parse["similar_requests"]),
                    "enhanced_parameters": enhanced_parse["enhanced_parameters"],
                    "generated_at": datetime.now(UTC).isoformat()
                }
                
                if enhanced_parse["similar_requests"]:
                    recommendations["historical_insights"] = [
                        {
                            "type": req.get("metadata", {}).get("resource_type", "unknown"),
                            "success": req.get("metadata", {}).get("success", False),
                            "similarity": req.get("score", 0.0),
                            "summary": req.get("summary", "")[:100]
                        }
                        for req in enhanced_parse["similar_requests"][:5]
                    ]
                
                span.set_attributes({
                    "recommendations.total_confidence": recommendations["total_confidence"],
                    "recommendations.similar_patterns": recommendations["similar_patterns"],
                    "recommendations.enhanced_parameters": len(recommendations["enhanced_parameters"])
                })
                
                return recommendations
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                self.logger.error("Failed to get parsing recommendations", error=str(e), exc_info=True)
                
                return {
                    "request": request_text,
                    "parsing_confidence": 0.0,
                    "vector_confidence_boost": 0.0,
                    "total_confidence": 0.0,
                    "recommendations": [],
                    "error": str(e),
                    "generated_at": datetime.now(UTC).isoformat()
                }