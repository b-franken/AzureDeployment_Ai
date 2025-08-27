from __future__ import annotations

import json
import uuid
from typing import Any

from opentelemetry import trace

from app.ai.agents.base import AgentContext
from app.ai.agents.provisioning import ProvisioningAgent, ProvisioningAgentConfig
from app.ai.nlu import parse_provision_request
from app.core.config import settings
from app.core.logging import get_logger
from app.memory.storage import get_async_store
from app.observability.app_insights import app_insights
from app.tools.base import Tool, ToolResult
from app.tools.provision.backends.avm_bicep.engine import BicepAvmBackend, ProvisionContext

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class IntelligentAzureProvision(Tool):
    """
    Production-grade Azure provisioning tool using AVM modules, intelligent agents,
    and comprehensive observability. Handles multi-resource deployments with
    natural language understanding and user memory persistence.
    
    Senior developer implementation following 2025+ best practices.
    """
    
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
                "description": "Natural language description of Azure resources to deploy. "
                "Examples: 'Create web app with SQL database', 'Deploy AKS cluster with monitoring'",
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
                "description": "Generate deployment plan without executing",
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
        self.avm_backend = BicepAvmBackend()
        logger.info(
            "IntelligentAzureProvision initialized with AVM backend",
            avm_version=getattr(self.avm_backend, 'version', 'latest'),
            observability_enabled=getattr(settings.observability, 'enabled', True),
        )

    async def run(self, **kwargs: Any) -> ToolResult:
        """
        Execute intelligent Azure resource provisioning with comprehensive observability.
        """
        request_text = kwargs.get("request", "").strip()
        correlation_id = kwargs.get("correlation_id") or str(uuid.uuid4())
        user_id = kwargs.get("user_id", "system")
        
        if not request_text:
            return {
                "ok": False,
                "summary": "Invalid request", 
                "output": "Request description is required for intelligent provisioning",
            }
            
        # Validate required parameters
        subscription_id = kwargs.get("subscription_id")
        resource_group = kwargs.get("resource_group")
        
        if not subscription_id:
            return {
                "ok": False,
                "summary": "Missing subscription_id",
                "output": "Azure subscription ID is required for provisioning",
            }
            
        if not resource_group:
            return {
                "ok": False,
                "summary": "Missing resource_group", 
                "output": "Resource group name is required for provisioning",
            }

        with tracer.start_as_current_span(
            "intelligent_azure_provision",
            attributes={
                "azure.subscription_id": kwargs.get("subscription_id", "unknown"),
                "azure.resource_group": kwargs.get("resource_group", "unknown"),
                "azure.location": kwargs.get("location", "westeurope"),
                "azure.environment": kwargs.get("environment", "dev"),
                "provision.dry_run": kwargs.get("dry_run", True),
                "provision.user_id": user_id,
                "provision.correlation_id": correlation_id,
                "provision.request_length": len(request_text),
            }
        ) as span:
            
            logger.info(
                "Starting intelligent Azure provisioning",
                request=request_text,
                correlation_id=correlation_id,
                user_id=user_id,
                subscription_id=kwargs.get("subscription_id"),
                resource_group=kwargs.get("resource_group"),
                location=kwargs.get("location", "westeurope"),
                environment=kwargs.get("environment", "dev"),
                dry_run=kwargs.get("dry_run", True),
            )

            try:
                # Step 1: Persist user request to memory for context
                await self._store_user_context(user_id, request_text, correlation_id)
                
                # Step 2: Parse natural language request
                nlu_result = await self._parse_request_with_context(user_id, request_text)
                span.set_attributes({
                    "nlu.intent": nlu_result.intent.value if hasattr(nlu_result, 'intent') else "unknown",
                    "nlu.resource_type": getattr(nlu_result, 'resource_type', 'unknown'),
                    "nlu.confidence": getattr(nlu_result, 'confidence', 0.0),
                })
                
                # Step 3: Create provisioning context
                provision_context = self._create_provision_context(kwargs, nlu_result)
                
                # Step 4: Initialize intelligent provisioning agent
                agent = await self._create_provisioning_agent(user_id, kwargs)
                
                # Step 5: Generate execution plan
                execution_plan = await agent.plan(request_text)
                span.set_attribute("agent.plan_steps", len(execution_plan.steps))
                
                logger.info(
                    "Generated intelligent execution plan",
                    correlation_id=correlation_id,
                    plan_steps=len(execution_plan.steps),
                    nlu_intent=getattr(nlu_result, 'intent', 'unknown'),
                    nlu_resource_type=getattr(nlu_result, 'resource_type', 'unknown'),
                )
                
                # Step 6: Execute plan using AVM backend
                if kwargs.get("dry_run", True):
                    result = await self._generate_plan_preview(
                        provision_context, nlu_result, correlation_id
                    )
                else:
                    result = await self._execute_deployment(
                        provision_context, nlu_result, agent, correlation_id
                    )
                
                # Step 7: Store deployment result in memory
                await self._store_deployment_result(user_id, result, correlation_id)
                
                app_insights.track_custom_event(
                    "intelligent_provision_completed",
                    {
                        "correlation_id": correlation_id,
                        "user_id": user_id,
                        "nlu_intent": getattr(nlu_result, 'intent', 'unknown'),
                        "nlu_resource_type": getattr(nlu_result, 'resource_type', 'unknown'),
                        "success": result.get("ok", False),
                        "dry_run": kwargs.get("dry_run", True),
                    }
                )
                
                return result
                
            except Exception as e:
                logger.error(
                    "Intelligent Azure provisioning failed",
                    correlation_id=correlation_id,
                    user_id=user_id,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    exc_info=True,
                )
                
                span.set_attributes({
                    "error.type": type(e).__name__,
                    "error.message": str(e),
                })
                
                app_insights.track_exception(e, {
                    "correlation_id": correlation_id,
                    "user_id": user_id,
                    "operation": "intelligent_provision",
                })
                
                return {
                    "ok": False,
                    "summary": f"Intelligent provisioning failed: {type(e).__name__}",
                    "output": f"Error during intelligent Azure provisioning: {str(e)}",
                }

    async def _store_user_context(self, user_id: str, request: str, correlation_id: str) -> None:
        """Store user request in memory for contextual understanding."""
        try:
            memory_store = await get_async_store()
            message_id = await memory_store.store_message(
                user_id=user_id,
                role="user",
                content=request,
                metadata={
                    "correlation_id": correlation_id,
                    "operation": "azure_provision",
                    "timestamp": "utc_now",
                },
            )
            
            logger.debug(
                "User context stored in memory",
                user_id=user_id,
                message_id=message_id,
                correlation_id=correlation_id,
            )
            
        except Exception as e:
            logger.warning(
                "Failed to store user context in memory",
                user_id=user_id,
                correlation_id=correlation_id,
                error=str(e),
            )

    async def _parse_request_with_context(self, user_id: str, request: str) -> dict[str, Any]:
        """Parse natural language request with user context from memory."""
        try:
            memory_store = await get_async_store()
            user_history = await memory_store.get_user_memory(
                user_id=user_id,
                limit=10,
                include_metadata=True,
            )
            
            logger.debug(
                "Retrieved user context for NLU parsing",
                user_id=user_id,
                history_messages=len(user_history),
            )
            
            # Enhanced NLU parsing with user context
            nlu_result = parse_provision_request(request)
            
            # Enrich with user preferences from history
            if user_history:
                nlu_result = self._enrich_with_user_preferences(nlu_result, user_history)
            
            logger.info(
                "Natural language request parsed successfully",
                user_id=user_id,
                products_detected=len(nlu_result.get("products", [])),
                resources_detected=len(nlu_result.get("resources", [])),
                context_enriched=len(user_history) > 0,
            )
            
            return nlu_result
            
        except Exception as e:
            logger.error(
                "Failed to parse request with context",
                user_id=user_id,
                error=str(e),
                exc_info=True,
            )
            return parse_provision_request(request)

    def _enrich_with_user_preferences(
        self, nlu_result: Any, user_history: list[dict[str, Any]]
    ) -> Any:
        """Enrich NLU result with user preferences from history."""
        # Extract user preferences from previous interactions
        preferred_locations = []
        preferred_environments = []
        
        for message in user_history:
            if message.get("role") == "user":
                content = message.get("content", "").lower()
                if "westeurope" in content:
                    preferred_locations.append("westeurope")
                elif "eastus" in content:
                    preferred_locations.append("eastus")
                    
                if "production" in content or "prod" in content:
                    preferred_environments.append("production")
                elif "staging" in content:
                    preferred_environments.append("staging")
        
        # For UnifiedParseResult, modify the context field to add preferences
        if hasattr(nlu_result, 'context'):
            if preferred_locations:
                nlu_result.context["preferred_location"] = preferred_locations[0]
            if preferred_environments:
                nlu_result.context["preferred_environment"] = preferred_environments[0]
        
        logger.debug(
            "Enriched NLU result with user preferences",
            preferred_locations=preferred_locations,
            preferred_environments=preferred_environments,
        )
        
        return nlu_result

    def _create_provision_context(self, kwargs: dict[str, Any], nlu_result: Any) -> ProvisionContext:
        """Create provisioning context from parameters and NLU results."""
        # Extract preferences from NLU result context
        preferred_location = None
        preferred_environment = None
        
        if hasattr(nlu_result, 'context'):
            preferred_location = nlu_result.context.get("preferred_location")
            preferred_environment = nlu_result.context.get("preferred_environment")
        
        location = kwargs.get("location") or preferred_location or "westeurope"
        environment = kwargs.get("environment") or preferred_environment or "dev"
        
        tags = {
            "CreatedBy": "IntelligentAzureProvision",
            "ManagedBy": "AVM-Bicep",
            "Environment": environment,
            **(kwargs.get("tags") or {}),
        }
        
        context = ProvisionContext(
            subscription_id=kwargs["subscription_id"],
            resource_group=kwargs["resource_group"],
            location=location,
            name_prefix=kwargs.get("name_prefix", "app"),
            environment=environment,
            tags=tags,
        )
        
        logger.debug(
            "Created provisioning context",
            subscription_id=context.subscription_id,
            resource_group=context.resource_group,
            location=context.location,
            environment=context.environment,
            name_prefix=context.name_prefix,
        )
        
        return context

    async def _create_provisioning_agent(
        self, user_id: str, kwargs: dict[str, Any]
    ) -> ProvisioningAgent:
        """Create intelligent provisioning agent with configuration."""
        config = ProvisioningAgentConfig(
            provider=kwargs.get("provider"),
            model=kwargs.get("model"), 
            environment=kwargs.get("environment", "dev"),
        )
        
        context = AgentContext(
            user_id=user_id,
            environment=kwargs.get("environment", "dev"),
            dry_run=kwargs.get("dry_run", True),
            metadata={
                "correlation_id": kwargs.get("correlation_id"),
                "subscription_id": kwargs.get("subscription_id"),
                "resource_group": kwargs.get("resource_group"),
            },
        )
        
        agent = ProvisioningAgent(user_id=user_id, context=context, config=config)
        
        logger.debug(
            "Created provisioning agent with context",
            user_id=user_id,
            provider=config.provider,
            model=config.model,
            environment=config.environment,
            dry_run=context.dry_run,
        )
        
        return agent

    async def _generate_plan_preview(
        self, 
        context: ProvisionContext, 
        nlu_result: dict[str, Any],
        correlation_id: str,
    ) -> ToolResult:
        """Generate deployment plan preview using AVM backend."""
        try:
            plan_preview = await self.avm_backend.plan_from_nlu(
                nlu_result, context, dry_run=True
            )
            
            cost_estimate = plan_preview.cost_estimate or {}
            monthly_cost = cost_estimate.get("monthly_estimate", 0.0)
            
            logger.info(
                "Generated AVM deployment plan preview",
                correlation_id=correlation_id,
                bicep_path=plan_preview.bicep_path,
                estimated_monthly_cost=monthly_cost,
                has_what_if=plan_preview.what_if is not None,
                validation_passed=plan_preview.validation_results.get("valid", False),
            )
            
            output_sections = [
                f"**Azure Deployment Plan Preview**",
                f"",
                f"**Deployment Context:**",
                f"- Resource Group: {context.resource_group}",
                f"- Location: {context.location}",
                f"- Environment: {context.environment}",
                f"- Estimated Monthly Cost: ${monthly_cost:.2f} USD",
                f"",
                f"## Azure Verified Module (AVM) Bicep Code",
                f"```bicep",
                plan_preview.rendered,
                f"```",
                f"",
            ]
            
            if plan_preview.what_if:
                output_sections.extend([
                    f"## What-If Analysis",
                    f"```",
                    plan_preview.what_if,
                    f"```",
                    f"",
                ])
            
            if cost_estimate:
                output_sections.extend([
                    f"## Cost Breakdown",
                    f"```json",
                    json.dumps(cost_estimate, indent=2),
                    f"```",
                    f"",
                ])
            
            output_sections.extend([
                f"## Next Steps",
                f"1. Review the AVM Bicep code and what-if analysis above",
                f"2. To execute deployment: Set `dry_run: false` and confirm",
                f"3. All resources follow Azure best practices via AVM modules",
                f"",
                f"**Note:** This deployment uses Azure Verified Modules (AVM) for security, compliance, and best practices.",
            ])
            
            return {
                "ok": True,
                "summary": f"AVM deployment plan generated - {getattr(nlu_result, 'resource_type', 'resource')} deployment",
                "output": "\n".join(output_sections),
            }
            
        except Exception as e:
            logger.error(
                "Failed to generate AVM plan preview",
                correlation_id=correlation_id,
                error=str(e),
                exc_info=True,
            )
            raise

    async def _execute_deployment(
        self,
        context: ProvisionContext,
        nlu_result: dict[str, Any], 
        agent: ProvisioningAgent,
        correlation_id: str,
    ) -> ToolResult:
        """Execute actual deployment using AVM backend and agent orchestration."""
        try:
            # Generate plan first
            plan_preview = await self.avm_backend.plan_from_nlu(
                nlu_result, context, dry_run=False
            )
            
            logger.info(
                "Starting AVM deployment execution",
                correlation_id=correlation_id,
                bicep_path=plan_preview.bicep_path,
                resource_group=context.resource_group,
            )
            
            # Execute deployment
            deployment_result = await self.avm_backend.apply(
                context, plan_preview.bicep_path
            )
            
            if deployment_result.get("status") == "succeeded":
                logger.info(
                    "AVM deployment completed successfully",
                    correlation_id=correlation_id,
                    deployment_id=deployment_result.get("deployment_id"),
                    duration=deployment_result.get("duration"),
                )
                
                output_sections = [
                    f"**Azure Deployment Completed Successfully**",
                    f"",
                    f"**Deployment Details:**",
                    f"- Deployment ID: `{deployment_result.get('deployment_id', 'Unknown')}`",
                    f"- Resource Group: {context.resource_group}",
                    f"- Location: {context.location}",
                    f"- Duration: {deployment_result.get('duration', 'Unknown')}",
                    f"- Status: ✅ Succeeded",
                    f"",
                    f"## Deployed Resources (AVM Modules)",
                    f"```json",
                    json.dumps(deployment_result.get("outputs", {}), indent=2),
                    f"```",
                    f"",
                    f"## Azure Verified Module (AVM) Bicep Code",
                    f"```bicep",
                    plan_preview.rendered,
                    f"```",
                    f"",
                    f"**Note:** All resources deployed using Azure Verified Modules (AVM) following Azure best practices.",
                ]
                
                return {
                    "ok": True,
                    "summary": f"AVM deployment succeeded - {getattr(nlu_result, 'resource_type', 'resource')} deployed",
                    "output": "\n".join(output_sections),
                }
            else:
                logger.error(
                    "AVM deployment failed",
                    correlation_id=correlation_id,
                    status=deployment_result.get("status"),
                    raw_result=deployment_result,
                )
                
                return {
                    "ok": False,
                    "summary": f"AVM deployment failed: {deployment_result.get('status')}",
                    "output": f"Deployment failed: {deployment_result.get('message', 'Unknown error')}",
                }
                
        except Exception as e:
            logger.error(
                "AVM deployment execution failed",
                correlation_id=correlation_id,
                error=str(e),
                exc_info=True,
            )
            raise

    async def _store_deployment_result(
        self, user_id: str, result: ToolResult, correlation_id: str
    ) -> None:
        """Store deployment result in user memory for future context."""
        try:
            memory_store = await get_async_store()
            
            summary = result.get("summary", "Deployment completed")
            success = result.get("ok", False)
            
            message_id = await memory_store.store_message(
                user_id=user_id,
                role="assistant",
                content=f"Deployment result: {summary}",
                metadata={
                    "correlation_id": correlation_id,
                    "operation": "azure_provision_result",
                    "success": success,
                    "timestamp": "utc_now",
                },
            )
            
            logger.debug(
                "Deployment result stored in user memory",
                user_id=user_id,
                message_id=message_id,
                correlation_id=correlation_id,
                success=success,
            )
            
        except Exception as e:
            logger.warning(
                "Failed to store deployment result in memory",
                user_id=user_id,
                correlation_id=correlation_id,
                error=str(e),
            )