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
from app.tools.azure.codegen.terraform import generate_terraform_code

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class IntelligentAzureProvision(Tool):
    """
    Intelligent Azure provisioning using AVM when available,
    with a reliable fallback to the Azure SDK tools from the repository
    (which authenticate via src/app/core/azure_auth.py).
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
            avm_version=getattr(self.avm_backend, "version", "latest"),
            observability_enabled=getattr(
                settings.observability, "enabled", True),
        )

    async def run(self, **kwargs: Any) -> ToolResult:
        """
        Execute intelligent Azure resource provisioning with comprehensive observability.
        Falls back to Azure SDK tools when AVM cannot render/resolve the resource.
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

        subscription_id = kwargs.get("subscription_id")
        if not subscription_id:
            return {
                "ok": False,
                "summary": "Missing subscription_id",
                "output": "Azure subscription ID is required for provisioning",
            }

        requested_rg = kwargs.get("resource_group")

        with tracer.start_as_current_span(
            "intelligent_azure_provision",
            attributes={
                "azure.subscription_id": subscription_id,
                "azure.resource_group": requested_rg or "unknown",
                "azure.location": kwargs.get("location", "westeurope"),
                "azure.environment": kwargs.get("environment", "dev"),
                "provision.dry_run": kwargs.get("dry_run", True),
                "provision.user_id": user_id,
                "provision.correlation_id": correlation_id,
                "provision.request_length": len(request_text),
            },
        ) as span:
            logger.info(
                "Starting intelligent Azure provisioning",
                request=request_text,
                correlation_id=correlation_id,
                user_id=user_id,
                subscription_id=subscription_id,
                resource_group=requested_rg,
                location=kwargs.get("location", "westeurope"),
                environment=kwargs.get("environment", "dev"),
                dry_run=kwargs.get("dry_run", True),
            )

            try:
                await self._store_user_context(user_id, request_text, correlation_id)

                nlu_result = await self._parse_request_with_context(user_id, request_text)
                logger.info(
                    "NLU parsing result",
                    resource_type=getattr(nlu_result, "resource_type", None),
                    resource_name=getattr(nlu_result, "resource_name", None),
                    context=getattr(nlu_result, "context", None),
                    parameters=getattr(nlu_result, "parameters", None),
                    correlation_id=correlation_id,
                )
                span.set_attributes(
                    {
                        "nlu.intent": (
                            nlu_result.intent.value if hasattr(
                                nlu_result, "intent") else "unknown"
                        ),
                        "nlu.resource_type": getattr(nlu_result, "resource_type", "unknown"),
                        "nlu.confidence": getattr(nlu_result, "confidence", 0.0),
                    }
                )

                if not requested_rg:
                    context = getattr(nlu_result, "context", {}) or {}
                    parameters = getattr(nlu_result, "parameters", {}) or {}

                    if getattr(nlu_result, "resource_type", "") == "resource_group":
                        inferred_rg = getattr(
                            nlu_result, "resource_name", None)
                    else:
                        inferred_rg = (
                            context.get("resource_group") or
                            parameters.get("resource_group") or
                            context.get("rg") or
                            parameters.get("rg")
                        )

                    if not inferred_rg:
                        import re
                        rg_patterns = [
                            r"(?:in|to|from)\s+resource\s+group\s+([\w-]+)",
                            r"resource[_-]group[\s=:]+([\w-]+)",
                            r"rg[\s=:]+([\w-]+)",
                        ]
                        for pattern in rg_patterns:
                            match = re.search(
                                pattern, request_text, re.IGNORECASE)
                            if match:
                                inferred_rg = match.group(1)
                                break

                    if inferred_rg:
                        kwargs["resource_group"] = inferred_rg
                        requested_rg = inferred_rg
                        logger.info(
                            "Extracted resource_group",
                            resource_group=inferred_rg,
                            correlation_id=correlation_id,
                        )

                if not requested_rg and getattr(nlu_result, "resource_type", "") != "resource_group":
                    return {
                        "ok": False,
                        "summary": "Missing resource_group",
                        "output": "Resource group name is required for provisioning",
                    }

                provision_context = self._create_provision_context(
                    kwargs, nlu_result)
                agent = await self._create_provisioning_agent(user_id, kwargs)

                execution_plan = await agent.plan(request_text)
                span.set_attribute("agent.plan_steps",
                                   len(execution_plan.steps))

                logger.info(
                    "Generated intelligent execution plan",
                    correlation_id=correlation_id,
                    plan_steps=len(execution_plan.steps),
                    nlu_intent=getattr(nlu_result, "intent", "unknown").value if hasattr(nlu_result, "intent") else "unknown",
                    nlu_resource_type=getattr(nlu_result, "resource_type", "unknown"),
                )

                preview_result = await self._generate_plan_preview(
                    provision_context, nlu_result, correlation_id, request_text
                )
                
                if kwargs.get("dry_run", True):
                    result = preview_result
                else:
                    deployment_result = await self._execute_deployment(
                        provision_context, nlu_result, agent, correlation_id, request_text
                    )
                    
                    combined_output_sections = []
                    
                    if preview_result.get("output"):
                        combined_output_sections.append("## Deployment Preview")
                        combined_output_sections.append(preview_result["output"])
                        combined_output_sections.append("")
                    
                    if deployment_result.get("output"):
                        combined_output_sections.append("## Deployment Execution")
                        combined_output_sections.append(deployment_result["output"])
                    
                    result = {
                        "ok": deployment_result.get("ok", False),
                        "summary": f"Deployment completed - {deployment_result.get('summary', '')}",
                        "output": "\n".join(combined_output_sections),
                        "preview_data": preview_result,
                        "deployment_data": deployment_result
                    }

                await self._store_deployment_result(user_id, result, correlation_id)

                app_insights.track_custom_event(
                    "intelligent_provision_completed",
                    {
                        "correlation_id": correlation_id,
                        "user_id": user_id,
                        "nlu_intent": getattr(nlu_result, "intent", "unknown"),
                        "nlu_resource_type": getattr(nlu_result, "resource_type", "unknown"),
                        "success": result.get("ok", False),
                        "dry_run": kwargs.get("dry_run", True),
                    },
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

                span.set_attributes(
                    {
                        "error.type": type(e).__name__,
                        "error.message": str(e),
                    }
                )

                app_insights.track_exception(
                    e,
                    {
                        "correlation_id": correlation_id,
                        "user_id": user_id,
                        "operation": "intelligent_provision",
                    },
                )

                return {
                    "ok": False,
                    "summary": f"Intelligent provisioning failed: {type(e).__name__}",
                    "output": f"Error during intelligent Azure provisioning: {e!s}",
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

    async def _parse_request_with_context(self, user_id: str, request: str) -> Any:
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

            nlu_result = parse_provision_request(request)

            if user_history:
                nlu_result = self._enrich_with_user_preferences(
                    nlu_result, user_history)

            logger.info(
                "Natural language request parsed successfully",
                user_id=user_id,
                intent=nlu_result.intent.value,
                resource_type=nlu_result.resource_type,
                resource_name=nlu_result.resource_name,
                confidence=nlu_result.confidence,
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
        preferred_locations: list[str] = []
        preferred_environments: list[str] = []

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

        if hasattr(nlu_result, "context"):
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
        preferred_location = None
        preferred_environment = None

        if hasattr(nlu_result, "context"):
            preferred_location = nlu_result.context.get("preferred_location")
            preferred_environment = nlu_result.context.get(
                "preferred_environment")

        location = kwargs.get("location") or preferred_location or "westeurope"
        environment = kwargs.get(
            "environment") or preferred_environment or "dev"

        tags = {
            "CreatedBy": "IntelligentAzureProvision",
            "ManagedBy": "AVM-Bicep",
            "Environment": environment,
            **(kwargs.get("tags") or {}),
        }

        context = ProvisionContext(
            subscription_id=kwargs["subscription_id"],
            resource_group=kwargs.get("resource_group"),
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

        agent = ProvisioningAgent(
            user_id=user_id, context=context, config=config)

        logger.debug(
            "Created provisioning agent with context",
            user_id=user_id,
            provider=config.provider,
            model=config.model,
            environment=config.environment,
            dry_run=context.dry_run,
        )

        return agent

    def _should_fallback_to_sdk(self, err: Exception, nlu_result: Any) -> bool:
        """
        Choose SDK fallback when AVM does not support the resource or when
        the AVM module/version resolution fails (e.g., KeyError in versions map).
        """
        if getattr(nlu_result, "resource_type", "") == "resource_group":
            return True

        msg = str(err).lower()
        patterns = [
            "unsupported resource type",
            "module not found",
            "unable to resolve module",
            "avm/res/",
            "br/public:avm",
            "keyerror",
            "no emitter for",
        ]
        return any(p in msg for p in patterns)

    def _map_resource_type_to_terraform_action(self, resource_type: str) -> str:
        """Map AVM resource types to Terraform action names."""
        mapping = {
            "resource_group": "create_rg",
            "storage_account": "create_storage",
            "webapp": "create_webapp",
            "web_app": "create_webapp",
            "app_service_plan": "create_webapp",
            "aks_cluster": "create_aks",
            "kubernetes_cluster": "create_aks",
            "vnet": "create_network",
            "virtual_network": "create_network",
            "subnet": "create_subnet",
            "log_analytics_workspace": "create_monitor",
            "key_vault": "create_keyvault",
            "sql_server": "create_sql_server",
            "sql_database": "create_sql_database",
            "cosmos_db": "create_cosmos",
            "cosmosdb": "create_cosmos",
            "container_registry": "create_acr",
            "acr": "create_acr",
            "Microsoft.Resources/resourceGroups": "create_rg",
            "Microsoft.Storage/storageAccounts": "create_storage",
            "Microsoft.Web/sites": "create_webapp",
            "Microsoft.Web/serverfarms": "create_webapp",
            "Microsoft.ContainerService/managedClusters": "create_aks",
            "Microsoft.Network/virtualNetworks": "create_network",
            "Microsoft.Network/virtualNetworks/subnets": "create_subnet",
            "Microsoft.OperationalInsights/workspaces": "create_monitor",
            "Microsoft.KeyVault/vaults": "create_keyvault",
            "Microsoft.Sql/servers": "create_sql_server",
            "Microsoft.Sql/servers/databases": "create_sql_database",
            "Microsoft.DocumentDB/databaseAccounts": "create_cosmos",
            "Microsoft.ContainerRegistry/registries": "create_acr",
            "api_management": "create_apim",
            "apim": "create_apim",
            "compute": "create_vm",
            "virtual_machine": "create_vm",
            "vm": "create_vm",
            "eventhub": "create_eventhub",
            "event_hub": "create_eventhub",
            "frontdoor": "create_frontdoor",
            "front_door": "create_frontdoor",
            "identity": "create_identity",
            "managed_identity": "create_identity",
            "policy": "create_policy",
            "redis": "create_redis",
            "redis_cache": "create_redis",
            "private_dns": "create_private_dns",
            "private_link": "create_private_link",
            "traffic_manager": "create_traffic_manager",
            "backup": "create_backup",
            "recovery_services": "create_backup"
        }
        return mapping.get(resource_type.lower(), resource_type.lower())

    async def _generate_plan_preview(
        self,
        context: ProvisionContext,
        nlu_result: Any,
        correlation_id: str,
        request_text: str,
    ) -> ToolResult:
        """Generate deployment plan preview using AVM backend or fall back to SDK on unsupported resources."""
        try:
            plan_preview = await self.avm_backend.plan_from_nlu(nlu_result, context, dry_run=True)

            cost_estimate = plan_preview.cost_estimate or {}
            monthly_cost = cost_estimate.get("monthly_estimate", 0.0)

            logger.info(
                "Generated AVM deployment plan preview",
                correlation_id=correlation_id,
                bicep_path=plan_preview.bicep_path,
                estimated_monthly_cost=monthly_cost,
                has_what_if=plan_preview.what_if is not None,
                validation_passed=plan_preview.validation_results.get(
                    "valid", False),
            )

            terraform_params = {
                "resource_group": context.resource_group,
                "location": context.location,
                "name": getattr(nlu_result, "resource_name", "myresource"),
                "environment": context.environment
            }
            
            resource_type = getattr(nlu_result, "resource_type", "")
            terraform_action = self._map_resource_type_to_terraform_action(resource_type)
            logger.debug(
                "Generating Terraform code",
                resource_type=resource_type,
                terraform_action=terraform_action,
                correlation_id=correlation_id
            )
            terraform_code = generate_terraform_code(terraform_action, terraform_params)

            output_sections = [
                "**Azure Deployment Plan Preview**",
                "",
                "**Deployment Context:**",
                f"- Resource Group: {context.resource_group}",
                f"- Location: {context.location}",
                f"- Environment: {context.environment}",
                f"- Estimated Monthly Cost: ${monthly_cost:.2f} USD",
                "",
                "## Azure Verified Module (AVM) Bicep Code",
                "```bicep",
                plan_preview.rendered,
                "```",
                "",
                "## Terraform Infrastructure Code",
                "```hcl",
                terraform_code,
                "```",
                "",
            ]

            if plan_preview.what_if:
                output_sections.extend(
                    [
                        "## What-If Analysis",
                        "```",
                        plan_preview.what_if,
                        "```",
                        "",
                    ]
                )

            if cost_estimate:
                output_sections.extend(
                    [
                        "## Cost Breakdown",
                        "```json",
                        json.dumps(cost_estimate, indent=2),
                        "```",
                        "",
                    ]
                )

            output_sections.extend(
                [
                    "## Next Steps",
                    "1. Review the AVM Bicep code and what-if analysis above",
                    "2. To execute deployment: Set `dry_run: false` and confirm",
                    "3. All resources follow Azure best practices via AVM modules",
                    "",
                    "**Note:** This deployment uses Azure Verified Modules (AVM) for security, compliance, and best practices.",
                ]
            )

            return {
                "ok": True,
                "summary": (
                    f"AVM deployment plan generated - "
                    f"{getattr(nlu_result, 'resource_type', 'resource')} deployment"
                ),
                "output": "\n".join(output_sections),
            }

        except Exception as e:
            if self._should_fallback_to_sdk(e, nlu_result):
                logger.info(
                    "AVM plan unsupported/unavailable; using SDK fallback",
                    correlation_id=correlation_id,
                    error=str(e),
                    resource_type=getattr(
                        nlu_result, "resource_type", "unknown"),
                )
                return await self._fallback_via_sdk(
                    request_text=request_text,
                    context=context,
                    nlu_result=nlu_result,
                    correlation_id=correlation_id,
                    dry_run=True,
                )
            logger.error(
                "Failed to generate AVM plan preview",
                correlation_id=correlation_id,
                error=str(e),
                exc_info=True,
            )
            raise

    async def _execute_deployment(self, context: ProvisionContext, nlu_result: Any, agent: ProvisioningAgent, correlation_id: str, request_text: str) -> ToolResult:
        try:
            plan_preview = await self.avm_backend.plan_from_nlu(nlu_result, context, dry_run=False)
            logger.info("Starting AVM deployment execution", correlation_id=correlation_id, bicep_path=plan_preview.bicep_path, resource_group=context.resource_group)
            deployment_result = await self.avm_backend.apply(context, plan_preview.bicep_path)
            if deployment_result.get("status") == "succeeded":
                cost_estimate = plan_preview.cost_estimate or {}
                monthly_cost = cost_estimate.get("monthly_estimate", 0.0)
                
                output_sections = [
                    "**Azure Deployment Completed Successfully**",
                    "",
                    "**Deployment Details:**",
                    f"- Deployment ID: `{deployment_result.get('deployment_id', 'Unknown')}`",
                    f"- Resource Group: {context.resource_group}",
                    f"- Location: {context.location}",
                    f"- Duration: {deployment_result.get('duration', 'Unknown')}",
                    f"- Estimated Monthly Cost: ${monthly_cost:.2f} USD",
                    "- Status:  Succeeded",
                    "",
                    "## Deployed Resources (AVM Modules)",
                    "```json",
                    json.dumps(deployment_result.get("outputs", {}), indent=2),
                    "```",
                    "",
                ]
                
                if cost_estimate:
                    output_sections.extend([
                        "## Cost Breakdown",
                        "```json",
                        json.dumps(cost_estimate, indent=2),
                        "```",
                        "",
                    ])
                
                output_sections.extend([
                    "## Azure Verified Module (AVM) Bicep Code",
                    "```bicep",
                    plan_preview.rendered,
                    "```",
                    "",
                    "**Note:** All resources deployed using Azure Verified Modules (AVM) following Azure best practices.",
                ])
                return {"ok": True, "summary": f"AVM deployment succeeded - {getattr(nlu_result, 'resource_type', 'resource')} deployed", "output": "\n".join(output_sections)}
            msg = str(deployment_result.get("message", "")).lower()
            if any(s in msg for s in ["azure cli not found", "no such file or directory", "az: not found"]):
                return await self._fallback_via_sdk(request_text=request_text, context=context, nlu_result=nlu_result, correlation_id=correlation_id, dry_run=False)
            logger.error("AVM deployment failed", correlation_id=correlation_id, status=deployment_result.get("status"), raw_result=deployment_result)
            return {"ok": False, "summary": f"AVM deployment failed: {deployment_result.get('status')}", "output": f"Deployment failed: {deployment_result.get('message', 'Unknown error')}"}
        except Exception as e:
            if self._should_fallback_to_sdk(e, nlu_result):
                logger.info("AVM execution unsupported/unavailable; using SDK fallback", correlation_id=correlation_id, error=str(e), resource_type=getattr(nlu_result, "resource_type", "unknown"))
                return await self._fallback_via_sdk(request_text=request_text, context=context, nlu_result=nlu_result, correlation_id=correlation_id, dry_run=False)
            logger.error("AVM deployment execution failed", correlation_id=correlation_id, error=str(e), exc_info=True)
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

    async def _fallback_via_sdk(
        self,
        request_text: str,
        context: ProvisionContext,
        nlu_result: Any,
        correlation_id: str,
        dry_run: bool,
    ) -> ToolResult:
        """
        Delegate to the in-repo Azure SDK tooling (no Azure CLI).
        Authentication flows through src/app/core/azure_auth.py as used by AzureProvision.
        """
        from app.tools.azure.tool import AzureProvision

        name_value = getattr(nlu_result, "resource_name",
                             None) or f"{context.name_prefix}-{context.environment}"

        if getattr(nlu_result, "resource_type", "") == "resource_group":
            if context.resource_group:
                name_value = context.resource_group

        params = {
            "subscription_id": context.subscription_id,
            "resource_group": context.resource_group,
            "location": context.location,
            "env": context.environment,
            "name": name_value,
            "tags": context.tags,
            "dry_run": dry_run,
            "correlation_id": correlation_id,
        }

        logger.info(
            "Invoking Azure SDK fallback",
            correlation_id=correlation_id,
            action_hint=request_text,
            params={k: v for k, v in params.items() if k != "tags"},
        )

        tool = AzureProvision()
        return await tool.run(action=request_text, **params)
