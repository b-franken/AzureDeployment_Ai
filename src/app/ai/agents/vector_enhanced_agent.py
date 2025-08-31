from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime, UTC

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .base import BaseAgent, AgentContext, AgentResult
from .types import AgentType, AgentStatus
from app.core.plugins.manager import PluginManager
from app.core.plugins.base import PluginContext
from app.memory.agent_persistence import get_agent_memory
from app.observability.app_insights import app_insights
from app.observability.distributed_tracing import get_service_tracer
from app.core.logging import get_logger

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)


class VectorEnhancedAgent(BaseAgent):
    def __init__(self, agent_name: str, plugin_manager: PluginManager):
        super().__init__(agent_name=agent_name, agent_type=AgentType.INTELLIGENT)
        self.plugin_manager = plugin_manager
        self.service_tracer = get_service_tracer(f"vector_enhanced_agent_{agent_name}")
        self.logger = logger.bind(component="vector_agent", agent_name=agent_name)
        
        self._vector_plugin_name = "vector_database"
        self._context_cache: Dict[str, Any] = {}
    
    async def initialize(self) -> None:
        async with self.service_tracer.start_distributed_span(
            operation_name="vector_agent_initialize",
            correlation_id=f"init_{self.agent_name}",
            attributes={
                "agent.name": self.agent_name,
                "agent.type": self.agent_type.value
            }
        ) as span:
            try:
                await super().initialize()
                
                vector_plugin = self.plugin_manager._registry.get_plugin(self._vector_plugin_name)
                if not vector_plugin or vector_plugin.status.value != "active":
                    raise RuntimeError(f"Vector database plugin not available or not active")
                
                span.set_attributes({
                    "vector.plugin_available": True,
                    "vector.plugin_status": vector_plugin.status.value
                })
                
                app_insights.track_custom_event(
                    "vector_enhanced_agent_initialized",
                    {
                        "agent_name": self.agent_name,
                        "agent_type": self.agent_type.value
                    }
                )
                
                self.logger.info("Vector-enhanced agent initialized")
                span.set_status(Status(StatusCode.OK))
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error("Failed to initialize vector-enhanced agent", error=str(e), exc_info=True)
                raise
    
    async def execute(self, context: AgentContext) -> AgentResult:
        async with self.service_tracer.start_distributed_span(
            operation_name="vector_agent_execute",
            correlation_id=context.correlation_id,
            user_id=context.user_id,
            attributes={
                "agent.name": self.agent_name,
                "context.has_query": bool(context.input_data.get("query"))
            }
        ) as span:
            start_time = datetime.now(UTC)
            
            try:
                query = context.input_data.get("query", "")
                operation_type = context.input_data.get("operation_type", "enhanced_processing")
                
                span.set_attributes({
                    "agent.operation_type": operation_type,
                    "agent.query_length": len(query)
                })
                
                relevant_context = await self._get_relevant_context(context, query, span)
                
                enhanced_context = context.model_copy()
                enhanced_context.input_data["relevant_context"] = relevant_context
                enhanced_context.input_data["vector_enhanced"] = True
                
                core_result = await self._execute_core_logic(enhanced_context, span)
                
                await self._store_interaction_context(context, core_result, span)
                
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                span.set_attributes({
                    "agent.execution_time_ms": execution_time,
                    "agent.success": core_result.success,
                    "agent.context_items": len(relevant_context.get("semantic_matches", []))
                })
                
                app_insights.track_custom_event(
                    "vector_enhanced_execution_completed",
                    {
                        "agent_name": self.agent_name,
                        "operation_type": operation_type,
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id
                    },
                    {
                        "execution_time_ms": execution_time,
                        "context_items_found": len(relevant_context.get("semantic_matches", []))
                    }
                )
                
                span.set_status(Status(StatusCode.OK))
                
                return AgentResult(
                    success=core_result.success,
                    data=core_result.data,
                    error_message=core_result.error_message,
                    execution_time_ms=execution_time,
                    metadata={
                        **core_result.metadata,
                        "vector_enhanced": True,
                        "relevant_context_found": len(relevant_context.get("semantic_matches", [])),
                        "context_sources": list(relevant_context.keys())
                    }
                )
                
            except Exception as e:
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                app_insights.track_exception(
                    e,
                    {
                        "agent_name": self.agent_name,
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id
                    }
                )
                
                self.logger.error(
                    "Vector-enhanced execution failed",
                    user_id=context.user_id,
                    correlation_id=context.correlation_id,
                    error=str(e),
                    exc_info=True
                )
                
                return AgentResult(
                    success=False,
                    error_message=str(e),
                    execution_time_ms=execution_time,
                    metadata={"error_type": type(e).__name__}
                )
    
    async def _get_relevant_context(self, context: AgentContext, query: str, span) -> Dict[str, Any]:
        with tracer.start_as_current_span("get_relevant_context") as context_span:
            if not query:
                context_span.set_attribute("context.empty_query", True)
                return {"semantic_matches": [], "stored_contexts": []}
            
            cache_key = f"{context.user_id}:{hash(query)}"
            if cache_key in self._context_cache:
                context_span.set_attribute("context.from_cache", True)
                return self._context_cache[cache_key]
            
            try:
                vector_context = PluginContext(
                    plugin_name=self._vector_plugin_name,
                    correlation_id=context.correlation_id,
                    execution_context={
                        "operation": "get_relevant_context",
                        "query": query,
                        "context_types": ["deployment", "conversation", "resource"]
                    },
                    user_context={
                        "user_id": context.user_id
                    }
                )
                
                plugin_result = await self.plugin_manager.execute_plugin(
                    self._vector_plugin_name, 
                    vector_context
                )
                
                if plugin_result.success:
                    relevant_context = plugin_result.result
                    self._context_cache[cache_key] = relevant_context
                    
                    context_span.set_attributes({
                        "context.semantic_matches": len(relevant_context.get("semantic_matches", [])),
                        "context.stored_contexts": len(relevant_context.get("stored_contexts", [])),
                        "context.from_cache": False
                    })
                    
                    return relevant_context
                else:
                    context_span.set_attribute("context.plugin_error", plugin_result.error_message)
                    self.logger.warning("Failed to get relevant context", error=plugin_result.error_message)
                    return {"semantic_matches": [], "stored_contexts": []}
                    
            except Exception as e:
                context_span.record_exception(e)
                self.logger.error("Error getting relevant context", error=str(e), exc_info=True)
                return {"semantic_matches": [], "stored_contexts": []}
    
    async def _execute_core_logic(self, context: AgentContext, span) -> AgentResult:
        with tracer.start_as_current_span("execute_core_logic") as core_span:
            operation_type = context.input_data.get("operation_type", "processing")
            relevant_context = context.input_data.get("relevant_context", {})
            
            core_span.set_attributes({
                "core.operation_type": operation_type,
                "core.has_context": bool(relevant_context.get("semantic_matches"))
            })
            
            if operation_type == "resource_analysis":
                return await self._analyze_resource_with_context(context, relevant_context, core_span)
            elif operation_type == "deployment_planning":
                return await self._plan_deployment_with_context(context, relevant_context, core_span)
            elif operation_type == "conversation_response":
                return await self._generate_contextual_response(context, relevant_context, core_span)
            else:
                return await self._default_processing(context, relevant_context, core_span)
    
    async def _analyze_resource_with_context(self, context: AgentContext, relevant_context: Dict[str, Any], span) -> AgentResult:
        resource_data = context.input_data.get("resource_data", {})
        similar_resources = relevant_context.get("semantic_matches", [])
        
        span.set_attributes({
            "analysis.resource_type": resource_data.get("type", "unknown"),
            "analysis.similar_resources": len(similar_resources)
        })
        
        analysis = {
            "resource_type": resource_data.get("type"),
            "analysis_timestamp": datetime.now(UTC).isoformat(),
            "similar_resources_found": len(similar_resources),
            "recommendations": [],
            "best_practices": [],
            "potential_issues": []
        }
        
        for similar in similar_resources[:3]:
            if similar.get("metadata", {}).get("success"):
                analysis["recommendations"].append(f"Based on similar deployment: {similar.get('summary', 'No summary')}")
        
        return AgentResult(
            success=True,
            data=analysis,
            metadata={"analysis_type": "vector_enhanced_resource_analysis"}
        )
    
    async def _plan_deployment_with_context(self, context: AgentContext, relevant_context: Dict[str, Any], span) -> AgentResult:
        deployment_request = context.input_data.get("deployment_request", "")
        historical_deployments = relevant_context.get("semantic_matches", [])
        
        span.set_attributes({
            "planning.request_length": len(deployment_request),
            "planning.historical_deployments": len(historical_deployments)
        })
        
        plan = {
            "deployment_plan": deployment_request,
            "created_at": datetime.now(UTC).isoformat(),
            "historical_insights": [],
            "risk_assessment": "low",
            "estimated_resources": []
        }
        
        for deployment in historical_deployments[:5]:
            insight = {
                "similarity_score": deployment.get("score", 0.0),
                "previous_outcome": deployment.get("metadata", {}).get("success", False),
                "key_learnings": deployment.get("summary", "")
            }
            plan["historical_insights"].append(insight)
        
        if any(not insight["previous_outcome"] for insight in plan["historical_insights"]):
            plan["risk_assessment"] = "medium"
        
        return AgentResult(
            success=True,
            data=plan,
            metadata={"planning_type": "vector_enhanced_deployment_planning"}
        )
    
    async def _generate_contextual_response(self, context: AgentContext, relevant_context: Dict[str, Any], span) -> AgentResult:
        user_query = context.input_data.get("query", "")
        conversation_history = relevant_context.get("stored_contexts", [])
        semantic_matches = relevant_context.get("semantic_matches", [])
        
        span.set_attributes({
            "response.query_length": len(user_query),
            "response.conversation_items": len(conversation_history),
            "response.semantic_matches": len(semantic_matches)
        })
        
        response = {
            "query": user_query,
            "response_timestamp": datetime.now(UTC).isoformat(),
            "context_aware": len(semantic_matches) > 0,
            "response_text": "",
            "confidence": 0.8
        }
        
        if semantic_matches:
            response["response_text"] = f"Based on your previous interactions and similar deployments, I can help you with: {user_query}"
            response["confidence"] = 0.9
        else:
            response["response_text"] = f"I'll help you with: {user_query}"
            response["confidence"] = 0.7
        
        return AgentResult(
            success=True,
            data=response,
            metadata={"response_type": "vector_enhanced_conversation"}
        )
    
    async def _default_processing(self, context: AgentContext, relevant_context: Dict[str, Any], span) -> AgentResult:
        span.set_attribute("processing.type", "default")
        
        result = {
            "processed_at": datetime.now(UTC).isoformat(),
            "input_data": context.input_data,
            "context_enhanced": bool(relevant_context.get("semantic_matches")),
            "processing_status": "completed"
        }
        
        return AgentResult(
            success=True,
            data=result,
            metadata={"processing_type": "default_vector_enhanced"}
        )
    
    async def _store_interaction_context(self, context: AgentContext, result: AgentResult, span) -> None:
        with tracer.start_as_current_span("store_interaction_context") as store_span:
            try:
                memory = await get_agent_memory()
                
                interaction_data = {
                    "agent_name": self.agent_name,
                    "user_query": context.input_data.get("query", ""),
                    "operation_type": context.input_data.get("operation_type", "unknown"),
                    "result_success": result.success,
                    "result_summary": str(result.data)[:500] if result.data else "",
                    "execution_time_ms": result.execution_time_ms,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "metadata": result.metadata
                }
                
                await memory.store_context(
                    user_id=context.user_id,
                    agent_name=self.agent_name,
                    context_key=f"interaction:{context.correlation_id}",
                    context_data=interaction_data,
                    correlation_id=context.correlation_id
                )
                
                if context.input_data.get("should_index", True) and result.success:
                    await self._index_interaction(context, result, store_span)
                
                store_span.set_status(Status(StatusCode.OK))
                
            except Exception as e:
                store_span.record_exception(e)
                self.logger.error("Failed to store interaction context", error=str(e), exc_info=True)
    
    async def _index_interaction(self, context: AgentContext, result: AgentResult, span) -> None:
        with tracer.start_as_current_span("index_interaction") as index_span:
            try:
                index_context = PluginContext(
                    plugin_name=self._vector_plugin_name,
                    correlation_id=context.correlation_id,
                    execution_context={
                        "operation": "index_resource",
                        "resource_data": {
                            "agent_interaction": True,
                            "agent_name": self.agent_name,
                            "user_query": context.input_data.get("query", ""),
                            "operation_type": context.input_data.get("operation_type"),
                            "result_data": result.data,
                            "success": result.success,
                            "timestamp": datetime.now(UTC).isoformat()
                        },
                        "resource_type": f"agent_interaction_{self.agent_name}",
                        "resource_id": context.correlation_id
                    }
                )
                
                plugin_result = await self.plugin_manager.execute_plugin(
                    self._vector_plugin_name,
                    index_context
                )
                
                if plugin_result.success:
                    index_span.set_attribute("indexing.success", True)
                    self.logger.debug("Interaction indexed for future retrieval")
                else:
                    index_span.set_attribute("indexing.success", False)
                    self.logger.warning("Failed to index interaction", error=plugin_result.error_message)
                
            except Exception as e:
                index_span.record_exception(e)
                self.logger.error("Error indexing interaction", error=str(e), exc_info=True)
    
    async def shutdown(self) -> None:
        with tracer.start_as_current_span("vector_agent_shutdown") as span:
            try:
                await super().shutdown()
                self._context_cache.clear()
                
                self.logger.info("Vector-enhanced agent shut down")
                span.set_status(Status(StatusCode.OK))
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error("Error during shutdown", error=str(e), exc_info=True)
                raise