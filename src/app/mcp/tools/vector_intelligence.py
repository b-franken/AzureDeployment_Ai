from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, UTC

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from app.core.plugins.manager import PluginManager
from app.core.plugins.base import PluginContext
from app.observability.app_insights import app_insights
from app.observability.distributed_tracing import get_service_tracer
from app.core.logging import get_logger
from ..schemas import MCPToolDefinition, MCPToolResult

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)


class VectorSearchRequest(BaseModel):
    query: str = Field(description="Search query for semantic similarity")
    limit: int = Field(default=10, description="Maximum number of results")
    threshold: float = Field(default=0.7, description="Similarity threshold (0.0-1.0)")
    context_types: List[str] = Field(default=["deployment", "resource", "conversation"], description="Types of context to search")
    user_id: Optional[str] = Field(default=None, description="User ID for personalized results")


class VectorIndexRequest(BaseModel):
    content: str = Field(description="Content to index")
    resource_type: str = Field(description="Type of resource being indexed")
    resource_id: Optional[str] = Field(default=None, description="Unique identifier for the resource")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class VectorRecommendationRequest(BaseModel):
    current_deployment: str = Field(description="Current deployment configuration or request")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")
    include_historical: bool = Field(default=True, description="Include historical deployment patterns")
    max_recommendations: int = Field(default=5, description="Maximum number of recommendations")


class VectorIntelligenceTools:
    def __init__(self, plugin_manager: PluginManager):
        self.plugin_manager = plugin_manager
        self.service_tracer = get_service_tracer("mcp_vector_intelligence")
        self.logger = logger.bind(component="mcp_vector_tools")
        
        self._vector_plugin_name = "vector_database"
    
    def get_tool_definitions(self) -> List[MCPToolDefinition]:
        return [
            MCPToolDefinition(
                name="semantic_search",
                description="Perform semantic search across deployment history, documentation, and conversations",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language search query"
                        },
                        "limit": {
                            "type": "integer",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 50,
                            "description": "Maximum number of results to return"
                        },
                        "threshold": {
                            "type": "number",
                            "default": 0.7,
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "Minimum similarity threshold"
                        },
                        "context_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": ["deployment", "resource", "conversation"],
                            "description": "Types of content to search through"
                        },
                        "user_id": {
                            "type": "string",
                            "description": "User ID for personalized search results"
                        }
                    },
                    "required": ["query"]
                }
            ),
            
            MCPToolDefinition(
                name="index_content",
                description="Index content for future semantic search and recommendations",
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Content to index (deployment configs, documentation, etc.)"
                        },
                        "resource_type": {
                            "type": "string",
                            "description": "Type of resource (deployment, documentation, conversation, etc.)"
                        },
                        "resource_id": {
                            "type": "string",
                            "description": "Unique identifier for the resource"
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Additional metadata for the indexed content"
                        }
                    },
                    "required": ["content", "resource_type"]
                }
            ),
            
            MCPToolDefinition(
                name="get_deployment_recommendations",
                description="Get AI-powered deployment recommendations based on historical data and best practices",
                parameters={
                    "type": "object",
                    "properties": {
                        "current_deployment": {
                            "type": "string",
                            "description": "Current deployment request or configuration"
                        },
                        "context": {
                            "type": "object",
                            "description": "Additional context (environment, constraints, requirements)"
                        },
                        "include_historical": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include recommendations based on historical deployments"
                        },
                        "max_recommendations": {
                            "type": "integer",
                            "default": 5,
                            "minimum": 1,
                            "maximum": 20,
                            "description": "Maximum number of recommendations to return"
                        }
                    },
                    "required": ["current_deployment"]
                }
            ),
            
            MCPToolDefinition(
                name="analyze_deployment_patterns",
                description="Analyze patterns in deployment history to identify trends and optimizations",
                parameters={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "User ID to analyze patterns for"
                        },
                        "time_range_days": {
                            "type": "integer",
                            "default": 30,
                            "minimum": 1,
                            "maximum": 365,
                            "description": "Number of days to analyze"
                        },
                        "resource_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific resource types to analyze"
                        },
                        "include_failed_deployments": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include failed deployments in analysis"
                        }
                    }
                }
            ),
            
            MCPToolDefinition(
                name="find_similar_deployments",
                description="Find deployments similar to a given configuration or request",
                parameters={
                    "type": "object",
                    "properties": {
                        "deployment_config": {
                            "type": "string",
                            "description": "Deployment configuration to find similarities for"
                        },
                        "similarity_threshold": {
                            "type": "number",
                            "default": 0.8,
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "Minimum similarity score"
                        },
                        "include_metadata": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include deployment metadata in results"
                        },
                        "user_id": {
                            "type": "string",
                            "description": "User ID to scope search to user's deployments"
                        }
                    },
                    "required": ["deployment_config"]
                }
            )
        ]
    
    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any], correlation_id: str) -> MCPToolResult:
        async with self.service_tracer.start_distributed_span(
            operation_name=f"mcp_vector_tool_{tool_name}",
            correlation_id=correlation_id,
            attributes={
                "tool.name": tool_name,
                "tool.parameters_count": len(parameters)
            }
        ) as span:
            start_time = datetime.now(UTC)
            
            try:
                if tool_name == "semantic_search":
                    result = await self._semantic_search(parameters, correlation_id, span)
                elif tool_name == "index_content":
                    result = await self._index_content(parameters, correlation_id, span)
                elif tool_name == "get_deployment_recommendations":
                    result = await self._get_deployment_recommendations(parameters, correlation_id, span)
                elif tool_name == "analyze_deployment_patterns":
                    result = await self._analyze_deployment_patterns(parameters, correlation_id, span)
                elif tool_name == "find_similar_deployments":
                    result = await self._find_similar_deployments(parameters, correlation_id, span)
                else:
                    raise ValueError(f"Unknown tool: {tool_name}")
                
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                span.set_attributes({
                    "tool.execution_time_ms": execution_time,
                    "tool.success": True,
                    "tool.result_size": len(str(result.data)) if result.data else 0
                })
                
                app_insights.track_custom_event(
                    "mcp_vector_tool_executed",
                    {
                        "tool_name": tool_name,
                        "correlation_id": correlation_id
                    },
                    {
                        "execution_time_ms": execution_time,
                        "parameters_count": len(parameters)
                    }
                )
                
                span.set_status(Status(StatusCode.OK))
                return result
                
            except Exception as e:
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                app_insights.track_exception(
                    e,
                    {
                        "tool_name": tool_name,
                        "correlation_id": correlation_id
                    }
                )
                
                self.logger.error(
                    "MCP vector tool execution failed",
                    tool_name=tool_name,
                    correlation_id=correlation_id,
                    error=str(e),
                    exc_info=True
                )
                
                return MCPToolResult(
                    success=False,
                    error_message=str(e),
                    execution_time_ms=execution_time
                )
    
    async def _semantic_search(self, parameters: Dict[str, Any], correlation_id: str, span) -> MCPToolResult:
        with tracer.start_as_current_span("semantic_search_execution") as search_span:
            request = VectorSearchRequest(**parameters)
            
            search_span.set_attributes({
                "search.query": request.query[:100],
                "search.limit": request.limit,
                "search.threshold": request.threshold,
                "search.context_types": request.context_types
            })
            
            plugin_context = PluginContext(
                plugin_name=self._vector_plugin_name,
                correlation_id=correlation_id,
                execution_context={
                    "operation": "semantic_search",
                    "query": request.query,
                    "limit": request.limit,
                    "threshold": request.threshold
                },
                user_context={
                    "user_id": request.user_id
                } if request.user_id else {}
            )
            
            plugin_result = await self.plugin_manager.execute_plugin(
                self._vector_plugin_name,
                plugin_context
            )
            
            if not plugin_result.success:
                raise RuntimeError(f"Vector plugin error: {plugin_result.error_message}")
            
            results = plugin_result.result
            
            search_span.set_attributes({
                "search.results_found": len(results),
                "search.plugin_execution_time": plugin_result.execution_time_ms
            })
            
            return MCPToolResult(
                success=True,
                data={
                    "results": results,
                    "query": request.query,
                    "total_found": len(results),
                    "search_metadata": {
                        "limit": request.limit,
                        "threshold": request.threshold,
                        "context_types": request.context_types
                    }
                },
                metadata={
                    "search_type": "semantic",
                    "vector_enhanced": True
                }
            )
    
    async def _index_content(self, parameters: Dict[str, Any], correlation_id: str, span) -> MCPToolResult:
        with tracer.start_as_current_span("index_content_execution") as index_span:
            request = VectorIndexRequest(**parameters)
            
            index_span.set_attributes({
                "index.resource_type": request.resource_type,
                "index.content_length": len(request.content),
                "index.has_metadata": bool(request.metadata)
            })
            
            plugin_context = PluginContext(
                plugin_name=self._vector_plugin_name,
                correlation_id=correlation_id,
                execution_context={
                    "operation": "index_resource",
                    "resource_data": {
                        "content": request.content,
                        "metadata": {
                            **request.metadata,
                            "indexed_at": datetime.now(UTC).isoformat(),
                            "mcp_indexed": True
                        }
                    },
                    "resource_type": request.resource_type,
                    "resource_id": request.resource_id
                }
            )
            
            plugin_result = await self.plugin_manager.execute_plugin(
                self._vector_plugin_name,
                plugin_context
            )
            
            if not plugin_result.success:
                raise RuntimeError(f"Vector plugin error: {plugin_result.error_message}")
            
            indexed_id = plugin_result.result.get("indexed_id")
            
            index_span.set_attributes({
                "index.indexed_id": indexed_id,
                "index.plugin_execution_time": plugin_result.execution_time_ms
            })
            
            return MCPToolResult(
                success=True,
                data={
                    "indexed_id": indexed_id,
                    "resource_type": request.resource_type,
                    "content_length": len(request.content),
                    "status": "indexed"
                },
                metadata={
                    "operation": "content_indexing",
                    "vector_enhanced": True
                }
            )
    
    async def _get_deployment_recommendations(self, parameters: Dict[str, Any], correlation_id: str, span) -> MCPToolResult:
        with tracer.start_as_current_span("deployment_recommendations_execution") as rec_span:
            request = VectorRecommendationRequest(**parameters)
            
            rec_span.set_attributes({
                "recommendations.deployment_length": len(request.current_deployment),
                "recommendations.include_historical": request.include_historical,
                "recommendations.max_recommendations": request.max_recommendations
            })
            
            similar_deployments = []
            if request.include_historical:
                search_context = PluginContext(
                    plugin_name=self._vector_plugin_name,
                    correlation_id=correlation_id,
                    execution_context={
                        "operation": "semantic_search",
                        "query": request.current_deployment,
                        "limit": request.max_recommendations * 2,
                        "threshold": 0.6
                    }
                )
                
                search_result = await self.plugin_manager.execute_plugin(
                    self._vector_plugin_name,
                    search_context
                )
                
                if search_result.success:
                    similar_deployments = search_result.result[:request.max_recommendations]
            
            recommendations = []
            for i, deployment in enumerate(similar_deployments):
                recommendation = {
                    "rank": i + 1,
                    "similarity_score": deployment.get("score", 0.0),
                    "deployment_summary": deployment.get("summary", ""),
                    "success_rate": deployment.get("metadata", {}).get("success", False),
                    "resource_types": deployment.get("metadata", {}).get("resource_types", []),
                    "recommendations": [
                        f"Consider using similar configuration patterns",
                        f"Review resource sizing from previous deployment"
                    ]
                }
                
                if deployment.get("metadata", {}).get("success"):
                    recommendation["recommendations"].append("This pattern has shown success in previous deployments")
                else:
                    recommendation["recommendations"].append("Review potential issues from similar failed deployment")
                
                recommendations.append(recommendation)
            
            rec_span.set_attributes({
                "recommendations.generated_count": len(recommendations),
                "recommendations.similar_deployments": len(similar_deployments)
            })
            
            return MCPToolResult(
                success=True,
                data={
                    "current_deployment": request.current_deployment,
                    "recommendations": recommendations,
                    "analysis": {
                        "similar_deployments_found": len(similar_deployments),
                        "recommendation_confidence": "high" if len(similar_deployments) >= 3 else "medium",
                        "analysis_timestamp": datetime.now(UTC).isoformat()
                    }
                },
                metadata={
                    "recommendation_type": "deployment_intelligence",
                    "vector_enhanced": True
                }
            )
    
    async def _analyze_deployment_patterns(self, parameters: Dict[str, Any], correlation_id: str, span) -> MCPToolResult:
        with tracer.start_as_current_span("pattern_analysis_execution") as pattern_span:
            user_id = parameters.get("user_id")
            time_range_days = parameters.get("time_range_days", 30)
            resource_types = parameters.get("resource_types", [])
            include_failed = parameters.get("include_failed_deployments", True)
            
            pattern_span.set_attributes({
                "analysis.user_id": user_id or "all_users",
                "analysis.time_range_days": time_range_days,
                "analysis.resource_types": resource_types,
                "analysis.include_failed": include_failed
            })
            
            context_context = PluginContext(
                plugin_name=self._vector_plugin_name,
                correlation_id=correlation_id,
                execution_context={
                    "operation": "get_relevant_context",
                    "query": "deployment patterns analysis historical data",
                    "context_types": ["deployment", "resource"]
                },
                user_context={
                    "user_id": user_id
                } if user_id else {}
            )
            
            context_result = await self.plugin_manager.execute_plugin(
                self._vector_plugin_name,
                context_context
            )
            
            patterns = {
                "most_common_resources": {},
                "success_rates_by_type": {},
                "deployment_trends": [],
                "frequent_configurations": [],
                "optimization_opportunities": []
            }
            
            if context_result.success:
                deployments = context_result.result.get("semantic_matches", [])
                
                for deployment in deployments:
                    metadata = deployment.get("metadata", {})
                    resource_type = metadata.get("resource_type", "unknown")
                    success = metadata.get("success", False)
                    
                    patterns["most_common_resources"][resource_type] = patterns["most_common_resources"].get(resource_type, 0) + 1
                    
                    if resource_type not in patterns["success_rates_by_type"]:
                        patterns["success_rates_by_type"][resource_type] = {"total": 0, "successful": 0}
                    
                    patterns["success_rates_by_type"][resource_type]["total"] += 1
                    if success:
                        patterns["success_rates_by_type"][resource_type]["successful"] += 1
                
                for resource_type, stats in patterns["success_rates_by_type"].items():
                    stats["success_rate"] = stats["successful"] / stats["total"] if stats["total"] > 0 else 0.0
                    
                    if stats["success_rate"] < 0.8 and stats["total"] >= 3:
                        patterns["optimization_opportunities"].append({
                            "resource_type": resource_type,
                            "issue": "Low success rate",
                            "success_rate": stats["success_rate"],
                            "recommendation": f"Review {resource_type} configuration patterns"
                        })
            
            pattern_span.set_attributes({
                "analysis.deployments_analyzed": len(deployments) if context_result.success else 0,
                "analysis.resource_types_found": len(patterns["most_common_resources"]),
                "analysis.opportunities_found": len(patterns["optimization_opportunities"])
            })
            
            return MCPToolResult(
                success=True,
                data={
                    "analysis_period": f"{time_range_days} days",
                    "patterns": patterns,
                    "insights": {
                        "total_deployments_analyzed": len(deployments) if context_result.success else 0,
                        "analysis_timestamp": datetime.now(UTC).isoformat()
                    }
                },
                metadata={
                    "analysis_type": "deployment_patterns",
                    "vector_enhanced": True
                }
            )
    
    async def _find_similar_deployments(self, parameters: Dict[str, Any], correlation_id: str, span) -> MCPToolResult:
        with tracer.start_as_current_span("similar_deployments_execution") as similar_span:
            deployment_config = parameters["deployment_config"]
            similarity_threshold = parameters.get("similarity_threshold", 0.8)
            include_metadata = parameters.get("include_metadata", True)
            user_id = parameters.get("user_id")
            
            similar_span.set_attributes({
                "similar.config_length": len(deployment_config),
                "similar.threshold": similarity_threshold,
                "similar.include_metadata": include_metadata,
                "similar.user_scoped": bool(user_id)
            })
            
            plugin_context = PluginContext(
                plugin_name=self._vector_plugin_name,
                correlation_id=correlation_id,
                execution_context={
                    "operation": "semantic_search",
                    "query": deployment_config,
                    "limit": 20,
                    "threshold": similarity_threshold
                },
                user_context={
                    "user_id": user_id
                } if user_id else {}
            )
            
            plugin_result = await self.plugin_manager.execute_plugin(
                self._vector_plugin_name,
                plugin_context
            )
            
            if not plugin_result.success:
                raise RuntimeError(f"Vector plugin error: {plugin_result.error_message}")
            
            similar_deployments = plugin_result.result
            
            formatted_results = []
            for deployment in similar_deployments:
                result = {
                    "similarity_score": deployment.get("score", 0.0),
                    "deployment_summary": deployment.get("summary", ""),
                    "deployment_id": deployment.get("id"),
                }
                
                if include_metadata:
                    result["metadata"] = deployment.get("metadata", {})
                    result["timestamp"] = deployment.get("timestamp")
                    result["resource_types"] = deployment.get("metadata", {}).get("resource_types", [])
                
                formatted_results.append(result)
            
            similar_span.set_attributes({
                "similar.results_found": len(formatted_results),
                "similar.plugin_execution_time": plugin_result.execution_time_ms
            })
            
            return MCPToolResult(
                success=True,
                data={
                    "input_deployment": deployment_config[:200] + "..." if len(deployment_config) > 200 else deployment_config,
                    "similar_deployments": formatted_results,
                    "search_parameters": {
                        "similarity_threshold": similarity_threshold,
                        "user_scoped": bool(user_id)
                    }
                },
                metadata={
                    "search_type": "deployment_similarity",
                    "vector_enhanced": True
                }
            )