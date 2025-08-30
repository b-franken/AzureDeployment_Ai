from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, Optional

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from app.observability.app_insights import app_insights
from app.observability.distributed_tracing import get_service_tracer, get_cross_service_tracer

from app.ai.nlu import parse_provision_request
from app.core.config import settings
from app.core.logging import get_logger
from app.memory.agent_persistence import get_agent_memory
from app.services.deployment_preview import DeploymentPreviewService
from app.tools.base import Tool, ToolResult

from app.core.provisioning import (
    ProvisionContext, 
    ExecutionResult,
    ProvisioningOrchestrator,
    AVMStrategy,
    SDKFallbackStrategy,
    DeploymentPhaseManager
)

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class IntelligentAzureProvision(Tool):
    name = "azure_provision"
    description = (
        "Intelligent Azure resource provisioning using Azure Verified Modules (AVM). "
        "Supports natural language requests, multi-resource deployments with dependency "
        "resolution, cost estimation, and user context memory. Follows Azure best practices "
        "and provides comprehensive observability."
    )

    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": (
                    "Natural language description of Azure resources to deploy. "
                    "Examples: 'Create web app with SQL database', "
                    "'Deploy AKS cluster with monitoring'"
                ),
            },
            "subscription_id": {
                "type": "string",
                "description": "Azure subscription ID",
            },
            "resource_group": {
                "type": "string",
                "description": "Target resource group name",
            },
            "location": {
                "type": "string",
                "enum": list(settings.azure.allowed_locations),
                "default": "westeurope",
                "description": "Azure region for deployment",
            },
            "environment": {
                "type": "string",
                "enum": ["dev", "staging", "production"],
                "default": "dev",
                "description": "Environment context for resource configuration",
            },
            "name_prefix": {
                "type": "string",
                "default": "app",
                "description": "Prefix for resource naming convention",
            },
            "dry_run": {
                "type": "boolean",
                "default": True,
                "description": "Generate deployment preview without executing (true for preview, false for actual deployment)",
            },
            "user_id": {
                "type": "string",
                "description": "User identifier for memory persistence",
            },
            "correlation_id": {
                "type": "string", 
                "description": "Request correlation ID for tracing",
            },
            "tags": {
                "type": "object",
                "description": "Additional resource tags",
                "additionalProperties": {"type": "string"},
            },
            "enable_monitoring": {
                "type": "boolean",
                "default": True,
                "description": "Enable Application Insights and Log Analytics integration",
            },
            "cost_optimization": {
                "type": "boolean",
                "default": True,
                "description": "Apply cost optimization recommendations",
            },
        },
        "required": ["request"],
        "additionalProperties": False,
    }

    def __init__(self) -> None:
        self.orchestrator = ProvisioningOrchestrator()
        self.phase_manager = DeploymentPhaseManager()
        self.preview_service = DeploymentPreviewService()
        
        self.orchestrator.register_strategy(AVMStrategy())
        self.orchestrator.register_strategy(SDKFallbackStrategy())
        
        self.service_tracer = get_service_tracer("intelligent_provision_service")
        self.cross_service_tracer = get_cross_service_tracer()
        
        logger.info(
            "IntelligentAzureProvision initialized with orchestrator",
            strategies_registered=len(self.orchestrator._strategies),
            observability_enabled=getattr(settings.observability, "enabled", True),
            distributed_tracing_enabled=True
        )

    async def run(self, **kwargs: Any) -> ToolResult:
        correlation_id = kwargs.get("correlation_id") or str(uuid.uuid4())
        user_id = kwargs.get("user_id", "system")
        
        async with self.service_tracer.start_distributed_span(
            operation_name="provision_orchestration",
            correlation_id=correlation_id,
            user_id=user_id,
            attributes={
                "request_type": "intelligent_provision",
                "environment": kwargs.get("environment", "dev"),
                "dry_run": kwargs.get("dry_run", True)
            }
        ) as span:
            try:
                await self.orchestrator.initialize_all_strategies()
                
                # Handle proceed commands by retrieving the original deployment context
                original_request = await self._handle_proceed_command(**kwargs)
                if original_request:
                    kwargs["request"] = original_request
                    logger.info("Proceed command detected, using stored deployment context", 
                              original_request=original_request[:100])
                
                validation_result = await self._validate_request(**kwargs)
                if not validation_result.success:
                    return validation_result.to_tool_result()
                
                context = await self._create_provision_context(**kwargs)
                
                parsing_result = await self._parse_request(context)
                if not parsing_result.success:
                    return parsing_result.to_tool_result()
                
                if context.dry_run:
                    preview_result = await self._generate_preview(context, parsing_result)
                    return preview_result.to_tool_result()
                
                planning_result = await self._create_deployment_plan(context)
                if not planning_result.success:
                    return planning_result.to_tool_result()
                
                execution_result = await self.orchestrator.execute_with_fallback(context)
                
                await self._store_execution_result(context, execution_result)
                
                span.set_attributes({
                    "execution.success": execution_result.success,
                    "execution.strategy_used": execution_result.strategy_used,
                    "execution.total_time_ms": execution_result.execution_time_ms
                })
                
                if execution_result.success:
                    span.set_status(Status(StatusCode.OK))
                else:
                    span.set_status(Status(StatusCode.ERROR, execution_result.error_message))
                
                return execution_result.to_tool_result()
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                app_insights.track_exception(
                    e,
                    {
                        "correlation_id": correlation_id,
                        "user_id": kwargs.get("user_id", "system"),
                        "operation": "intelligent_azure_provision"
                    }
                )
                
                return {
                    "ok": False,
                    "summary": "Unexpected error during provisioning",
                    "output": str(e),
                    "correlation_id": correlation_id
                }

    async def _validate_request(self, **kwargs: Any) -> ExecutionResult:
        with tracer.start_as_current_span("provision_validate_request") as span:
            request_text = kwargs.get("request", "").strip()
            user_id = kwargs.get("user_id", "system")
            
            span.set_attributes({
                "validation.request_length": len(request_text),
                "validation.user_id": user_id,
                "validation.has_subscription_id": bool(kwargs.get("subscription_id"))
            })
            
            if not request_text:
                error_msg = "Request description is required for intelligent provisioning"
                span.set_status(Status(StatusCode.ERROR, error_msg))
                
                app_insights.track_custom_event(
                    "provision_validation_failed",
                    {"reason": "empty_request", "user_id": user_id}
                )
                
                return ExecutionResult.failure_result(
                    strategy="validation",
                    error=error_msg
                )
            
            subscription_id = kwargs.get("subscription_id")
            if not subscription_id:
                error_msg = "Azure subscription ID is required for provisioning"
                span.set_status(Status(StatusCode.ERROR, error_msg))
                
                app_insights.track_custom_event(
                    "provision_validation_failed", 
                    {"reason": "missing_subscription_id", "user_id": user_id}
                )
                
                return ExecutionResult.failure_result(
                    strategy="validation",
                    error=error_msg
                )
            
            span.set_status(Status(StatusCode.OK))
            
            app_insights.track_custom_event(
                "provision_validation_passed",
                {
                    "user_id": user_id,
                    "request_preview": request_text[:100]
                },
                {"request_length": len(request_text)}
            )
            
            return ExecutionResult.success_result(
                strategy="validation",
                data={"validated": True}
            )

    async def _create_provision_context(self, **kwargs: Any) -> ProvisionContext:
        with tracer.start_as_current_span("provision_create_context") as span:
            correlation_id = kwargs.get("correlation_id") or str(uuid.uuid4())
            
            context = ProvisionContext(
                correlation_id=correlation_id,
                request_text=kwargs.get("request", "").strip(),
                user_id=kwargs.get("user_id", "system"),
                subscription_id=kwargs.get("subscription_id"),
                resource_group=kwargs.get("resource_group"),
                location=kwargs.get("location", "westeurope"),
                environment=kwargs.get("environment", "dev"),
                name_prefix=kwargs.get("name_prefix", "app"),
                dry_run=kwargs.get("dry_run", True),
                tags=kwargs.get("tags", {}),
                enable_monitoring=kwargs.get("enable_monitoring", True),
                cost_optimization=kwargs.get("cost_optimization", True),
                conversation_context=kwargs.get("conversation_context", [])
            )
            
            initial_phase = self.phase_manager.determine_provisioning_phase(context)
            context.advance_phase(initial_phase)
            
            initial_phase_value = initial_phase.value if hasattr(initial_phase, 'value') else str(initial_phase)
            
            span.set_attributes({
                "context.user_id": context.user_id,
                "context.correlation_id": context.correlation_id,
                "context.initial_phase": initial_phase_value,
                "context.dry_run": context.dry_run,
                "context.environment": context.environment
            })
            span.set_status(Status(StatusCode.OK))
            
            app_insights.track_custom_event(
                "provision_context_created",
                {
                    "user_id": context.user_id,
                    "correlation_id": context.correlation_id,
                    "initial_phase": initial_phase_value,
                    "environment": context.environment,
                    "dry_run": str(context.dry_run)
                }
            )
            
            return context

    async def _parse_request(self, context: ProvisionContext) -> ExecutionResult:
        async with self.service_tracer.start_distributed_span(
            operation_name="parse_request",
            correlation_id=context.correlation_id,
            user_id=context.user_id,
            attributes={
                "request_length": len(context.request_text),
                "environment": context.environment
            }
        ) as span:
            try:
                await self._store_user_context(context)
                
                nlu_context = await self.cross_service_tracer.trace_cross_service_call(
                    from_service="intelligent_provision_service",
                    to_service="nlu_service", 
                    operation="parse_provision_request",
                    correlation_id=context.correlation_id,
                    user_id=context.user_id,
                    payload={"request_text": context.request_text[:100]}
                )
                
                nlu_result = parse_provision_request(context.request_text)
                
                if hasattr(nlu_result, 'resources') and nlu_result.resources:
                    context.parsed_resources = nlu_result.resources
                elif hasattr(nlu_result, 'resource_type') and nlu_result.resource_type:
                    context.parsed_resources = [{
                        "resource_type": nlu_result.resource_type,
                        "resource_name": getattr(nlu_result, 'resource_name', 'unnamed'),
                        "parameters": getattr(nlu_result, 'parameters', {})
                    }]
                
                intent_value = getattr(nlu_result, 'intent', 'unknown')
                if hasattr(intent_value, 'value'):
                    intent_value = intent_value.value
                    
                context.execution_metadata.update({
                    "nlu_intent": str(intent_value),
                    "nlu_confidence": getattr(nlu_result, 'confidence', 0.0),
                    "parsing_timestamp": datetime.now(UTC).isoformat()
                })
                
                span.set_attributes({
                    "parsing.success": True,
                    "parsing.resources_found": len(context.parsed_resources),
                    "parsing.intent": context.execution_metadata.get("nlu_intent", "unknown")
                })
                span.set_status(Status(StatusCode.OK))
                
                app_insights.track_custom_event(
                    "provision_parsing_succeeded",
                    {
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id,
                        "intent": context.execution_metadata.get("nlu_intent", "unknown")
                    },
                    {
                        "resources_found": len(context.parsed_resources),
                        "confidence": context.execution_metadata.get("nlu_confidence", 0.0)
                    }
                )
                
                return ExecutionResult.success_result(
                    strategy="parsing",
                    data=context.parsed_resources
                )
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                app_insights.track_exception(
                    e,
                    {
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id,
                        "operation": "request_parsing"
                    }
                )
                
                return ExecutionResult.failure_result(
                    strategy="parsing",
                    error=f"Failed to parse request: {str(e)}"
                )

    async def _generate_preview(self, context: ProvisionContext, parsing_result: ExecutionResult) -> ExecutionResult:
        async with self.service_tracer.start_distributed_span(
            operation_name="generate_preview",
            correlation_id=context.correlation_id,
            user_id=context.user_id,
            attributes={
                "preview_type": "deployment_preview",
                "environment": context.environment
            }
        ) as span:
            try:
                nlu_result = parse_provision_request(context.request_text)
                
                preview_response = await self.preview_service.generate_preview_response(
                    nlu_result=nlu_result,
                    subscription_id=context.subscription_id,
                    resource_group=context.resource_group,
                    location=context.location,
                    environment=context.environment
                )
                
                span.set_attributes({
                    "preview.success": True,
                    "preview.resource_type": nlu_result.resource_type,
                    "preview.resource_name": nlu_result.resource_name or "unnamed"
                })
                span.set_status(Status(StatusCode.OK))
                
                app_insights.track_custom_event(
                    "deployment_preview_generated",
                    {
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id,
                        "resource_type": nlu_result.resource_type,
                        "environment": context.environment
                    }
                )
                
                return ExecutionResult.success_result(
                    strategy="preview_generation",
                    data={"preview_response": preview_response},
                    output=preview_response
                )
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                app_insights.track_exception(
                    e,
                    {
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id,
                        "operation": "preview_generation"
                    }
                )
                
                return ExecutionResult.failure_result(
                    strategy="preview_generation",
                    error=f"Failed to generate preview: {str(e)}"
                )

    async def _handle_proceed_command(self, **kwargs: Any) -> str | None:
        """Handle proceed commands by retrieving the original deployment context from agent memory."""
        request_text = kwargs.get("request", "").strip().lower()
        proceed_keywords = ["proceed", "confirm", "deploy it", "deploy now", "yes deploy", "go ahead"]
        
        if request_text not in proceed_keywords:
            return None
            
        user_id = kwargs.get("user_id", "system")
        correlation_id = kwargs.get("correlation_id")
        
        try:
            memory = await get_agent_memory()
            
            # Get the most recent deployment context
            conversation_history = await memory.get_context(
                user_id=user_id,
                agent_name="intelligent_provision",
                context_key="conversation_history"
            ) or []
            
            # Find the most recent deployment request (not a proceed command)
            for entry in reversed(conversation_history):
                if isinstance(entry, dict) and "request" in entry:
                    request = entry["request"].strip().lower()
                    if request not in proceed_keywords and any(
                        keyword in request for keyword in ["create", "deploy", "provision", "make", "add"]
                    ):
                        logger.info(
                            "Found original deployment request from conversation history",
                            original_request=entry["request"][:100],
                            correlation_id=correlation_id
                        )
                        return entry["request"]
            
            # Fallback: look at conversation context from the current request
            conversation_context = kwargs.get("conversation_context", [])
            for entry in reversed(conversation_context):
                if isinstance(entry, dict) and entry.get("role") == "user":
                    content = entry.get("content", "").strip().lower()
                    if content not in proceed_keywords and any(
                        keyword in content for keyword in ["create", "deploy", "provision", "make", "add"]
                    ):
                        logger.info(
                            "Found original deployment request from conversation context",
                            original_request=entry["content"][:100],
                            correlation_id=correlation_id
                        )
                        return entry["content"]
            
            logger.warning(
                "Proceed command detected but no original deployment request found",
                user_id=user_id,
                correlation_id=correlation_id
            )
            return None
            
        except Exception as e:
            logger.error(
                "Failed to retrieve deployment context for proceed command",
                error=str(e),
                user_id=user_id,
                correlation_id=correlation_id
            )
            return None

    async def _create_deployment_plan(self, context: ProvisionContext) -> ExecutionResult:
        with tracer.start_as_current_span("provision_create_deployment_plan") as span:
            span.set_attributes({
                "context.user_id": context.user_id,
                "context.correlation_id": context.correlation_id,
                "planning.resources_count": len(context.parsed_resources)
            })
            
            try:
                if not context.parsed_resources:
                    error_msg = "No resources to plan deployment for"
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    
                    return ExecutionResult.failure_result(
                        strategy="planning",
                        error=error_msg
                    )
                
                deployment_plan = {
                    "resources": context.parsed_resources,
                    "deployment_order": [r.get("resource_name", f"resource_{i}") for i, r in enumerate(context.parsed_resources)],
                    "parallel_groups": [],
                    "estimated_time_minutes": len(context.parsed_resources) * 5,
                    "prerequisites": [],
                    "warnings": [],
                    "created_at": datetime.now(UTC).isoformat(),
                    "environment": context.environment,
                    "dry_run": context.dry_run
                }
                
                if context.cost_optimization:
                    deployment_plan["optimizations"] = [
                        "Use basic SKUs for development environment",
                        "Enable auto-scaling where applicable", 
                        "Configure cost alerts"
                    ]
                
                context.deployment_plan = deployment_plan
                context.execution_metadata["planning_completed"] = True
                
                span.set_attributes({
                    "planning.success": True,
                    "planning.estimated_time_minutes": deployment_plan["estimated_time_minutes"],
                    "planning.has_optimizations": context.cost_optimization
                })
                span.set_status(Status(StatusCode.OK))
                
                app_insights.track_custom_event(
                    "provision_planning_succeeded",
                    {
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id,
                        "environment": context.environment
                    },
                    {
                        "resources_count": len(context.parsed_resources),
                        "estimated_time_minutes": deployment_plan["estimated_time_minutes"]
                    }
                )
                
                return ExecutionResult.success_result(
                    strategy="planning",
                    data=deployment_plan
                )
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                
                app_insights.track_exception(
                    e,
                    {
                        "user_id": context.user_id,
                        "correlation_id": context.correlation_id,
                        "operation": "deployment_planning"
                    }
                )
                
                return ExecutionResult.failure_result(
                    strategy="planning",
                    error=f"Failed to create deployment plan: {str(e)}"
                )

    async def _store_user_context(self, context: ProvisionContext) -> None:
        async with self.service_tracer.start_distributed_span(
            operation_name="store_user_context",
            correlation_id=context.correlation_id,
            user_id=context.user_id,
            attributes={
                "storage_type": "agent_memory",
                "persistence_layer": "postgresql"
            }
        ) as span:
            try:
                memory_context = await self.cross_service_tracer.trace_cross_service_call(
                    from_service="intelligent_provision_service",
                    to_service="agent_memory_service",
                    operation="store_user_context",
                    correlation_id=context.correlation_id,
                    user_id=context.user_id,
                    payload={"operation": "user_context_storage"}
                )
                
                memory = await get_agent_memory()
                
                user_context = {
                    "last_request": context.request_text,
                    "last_activity": datetime.now(UTC).isoformat(),
                    "correlation_id": context.correlation_id,
                    "environment_preference": context.environment,
                    "subscription_id": context.subscription_id,
                    "resource_group": context.resource_group,
                    "location": context.location,
                    "parsed_resources_count": len(context.parsed_resources),
                    "has_deployment_plan": bool(context.deployment_plan)
                }
                
                await memory.store_context(
                    user_id=context.user_id,
                    agent_name="intelligent_provision",
                    context_key="user_context",
                    context_data=user_context,
                    correlation_id=context.correlation_id,
                    ttl=timedelta(days=7)
                )
                
                conversation_entry = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "correlation_id": context.correlation_id,
                    "request": context.request_text,
                    "user_id": context.user_id
                }
                
                existing_conversation = await memory.get_context(
                    user_id=context.user_id,
                    agent_name="intelligent_provision",
                    context_key="conversation_history"
                ) or []
                
                if isinstance(existing_conversation, list):
                    existing_conversation.append(conversation_entry)
                    if len(existing_conversation) > 50:
                        existing_conversation = existing_conversation[-50:]
                else:
                    existing_conversation = [conversation_entry]
                
                await memory.store_context(
                    user_id=context.user_id,
                    agent_name="intelligent_provision",
                    context_key="conversation_history",
                    context_data=existing_conversation,
                    correlation_id=context.correlation_id,
                    ttl=timedelta(days=7)
                )
                
                span.set_attributes({
                    "storage.user_id": context.user_id,
                    "storage.correlation_id": context.correlation_id,
                    "storage.conversation_length": len(existing_conversation)
                })
                span.set_status(Status(StatusCode.OK))
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.warning(
                    "Failed to store user context",
                    user_id=context.user_id,
                    correlation_id=context.correlation_id,
                    error=str(e)
                )

    async def _store_execution_result(self, context: ProvisionContext, result: ExecutionResult) -> None:
        with tracer.start_as_current_span("provision_store_execution_result") as span:
            try:
                memory = await get_agent_memory()
                
                execution_record = {
                    "correlation_id": context.correlation_id,
                    "user_id": context.user_id,
                    "success": result.success,
                    "strategy_used": result.strategy_used,
                    "execution_time_ms": result.execution_time_ms,
                    "resources_affected": result.resources_affected,
                    "error_message": result.error_message,
                    "warnings": result.warnings,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "context_summary": context.get_execution_summary()
                }
                
                await memory.store_execution_context(
                    user_id=context.user_id,
                    correlation_id=context.correlation_id,
                    context_data=execution_record,
                    ttl=timedelta(days=30)
                )
                
                span.set_attributes({
                    "storage.correlation_id": context.correlation_id,
                    "storage.success": result.success,
                    "storage.strategy_used": result.strategy_used
                })
                span.set_status(Status(StatusCode.OK))
                
                app_insights.track_custom_event(
                    "provision_execution_result_stored",
                    {
                        "correlation_id": context.correlation_id,
                        "user_id": context.user_id,
                        "success": str(result.success),
                        "strategy_used": result.strategy_used
                    },
                    {
                        "execution_time_ms": result.execution_time_ms,
                        "resources_affected": len(result.resources_affected)
                    }
                )
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.warning(
                    "Failed to store execution result",
                    correlation_id=context.correlation_id,
                    error=str(e)
                )