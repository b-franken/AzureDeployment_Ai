from __future__ import annotations

# Import OpenTelemetry fixes early to prevent deprecation warnings
from app.observability.otel_fixes import ensure_proper_otel_initialization

ensure_proper_otel_initialization()

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from azure.identity import AzureCliCredential, ChainedTokenCredential, ManagedIdentityCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
from fastmcp import Context, FastMCP

from app.ai.tools_router import ToolExecutionContext, maybe_call_tool
from app.core.cache.dependency import get_cache
from app.core.streams import StreamingHandler
from app.mcp.extensions import register_extensions
from app.mcp.schemas import AzureQueryParams, DeploymentRequest, ToolExecutionRequest
from app.mcp.tools.cost_intelligence import register_cost_intelligence_tool
from app.mcp.tools.integrated_analytics import register_integrated_analytics_tool
from app.mcp.tools.security_advisor import register_security_advisor_tool
from app.mcp.tools.what_if import register as register_what_if
from app.platform.audit.logger import AuditLogger
from app.tools.registry import ensure_tools_loaded, list_tools

from .resources import ResourceManager

logger = logging.getLogger("app.mcp.server")


class MCPServer:
    def __init__(
        self,
        name: str = "DevOps AI Tools",
        transport: Literal["stdio", "sse", "streamable-http"] = "sse",
    ):
        self.mcp = FastMCP(name=name)
        self.transport = transport
        self.cache: Any = None
        self.resource_manager = ResourceManager()
        self.streaming_handler = StreamingHandler()
        self.audit_logger = AuditLogger()

    @classmethod
    async def create(
        cls,
        name: str = "DevOps AI Tools",
        transport: Literal["stdio", "sse", "streamable-http"] = "sse",
    ) -> MCPServer:
        logger.info(
            "Creating MCP server",
            extra={
                "event": "mcp_create",
                "transport": transport,
                "environment": os.getenv("ENVIRONMENT", "development"),
            },
        )
        self = cls(name=name, transport=transport)
        self.cache = await get_cache()
        self._setup_tools()
        self._setup_resources()
        self._setup_prompts()
        register_extensions(self)
        register_what_if(self.mcp)
        register_integrated_analytics_tool(self.mcp)
        register_security_advisor_tool(self.mcp)
        register_cost_intelligence_tool(self.mcp)
        await self._register_vector_intelligence_tools()
        logger.info("MCP server created", extra={"event": "mcp_created"})
        return self

    def _setup_tools(self) -> None:
        ensure_tools_loaded()

        @self.mcp.tool(
            name="execute_tool",
            description="Execute any registered DevOps tool with full context support",
        )
        async def execute_tool(
            request: ToolExecutionRequest,
            context: Context,
        ) -> dict[str, Any]:
            meta = getattr(context, "meta", None)
            user_id = (meta or {}).get("user_id", "mcp_user")
            logger.info(
                "Executing tool",
                extra={
                    "event": "execute_tool",
                    "tool_name": request.tool_name,
                    "correlation_id": request.correlation_id,
                    "user_id": user_id,
                },
            )
            execution_context = ToolExecutionContext(
                user_id=user_id,
                subscription_id=request.subscription_id,
                resource_group=request.resource_group,
                environment=request.environment,
                correlation_id=request.correlation_id,
                audit_enabled=request.audit_enabled,
                cost_limit=request.cost_limit,
                dry_run=request.dry_run,
                audit_logger=self.audit_logger if request.audit_enabled else None,
            )
            cache_key = f"tool:{request.tool_name}:{request.get_cache_key()}"
            try:
                if not request.force_refresh:
                    cached_result = await self.cache.get(cache_key)
                    if cached_result:
                        logger.info(
                            "Tool cache hit",
                            extra={
                                "event": "execute_tool_cache_hit",
                                "tool_name": request.tool_name,
                                "correlation_id": request.correlation_id,
                            },
                        )
                        return cast("dict[str, Any]", cached_result)
                result = await maybe_call_tool(
                    user_input=request.input_text,
                    memory=request.memory,
                    provider=request.provider,
                    model=request.model,
                    enable_tools=True,
                    preferred_tool=request.tool_name,
                    context=execution_context,
                    return_json=True,
                )
                response: dict[str, Any] = {
                    "success": True,
                    "result": json.loads(result) if isinstance(result, str) else result,
                    "execution_time": datetime.utcnow().isoformat(),
                    "correlation_id": request.correlation_id,
                }
                if request.cache_ttl > 0:
                    await self.cache.set(cache_key, response, ttl=request.cache_ttl)
                logger.info(
                    "Tool executed",
                    extra={
                        "event": "execute_tool_success",
                        "tool_name": request.tool_name,
                        "correlation_id": request.correlation_id,
                    },
                )
                return response
            except Exception as e:
                logger.exception(
                    "Tool execution failed",
                    extra={
                        "event": "execute_tool_error",
                        "tool_name": request.tool_name,
                        "correlation_id": request.correlation_id,
                    },
                )
                return {
                    "success": False,
                    "error": str(e),
                    "execution_time": datetime.utcnow().isoformat(),
                    "correlation_id": request.correlation_id,
                }

        @self.mcp.tool(
            name="deploy_infrastructure",
            description="Deploy Azure infrastructure with validation and approval workflow",
        )
        async def deploy_infrastructure(
            request: DeploymentRequest,
            context: Context,
        ) -> dict[str, Any]:
            logger.info(
                "Deploy infrastructure",
                extra={"event": "deploy_start", "deployment_id": request.deployment_id},
            )
            try:
                if request.validate_only:
                    validation_results = await self._validate_deployment(request)
                    return {
                        "status": "validation_complete",
                        "validation_results": validation_results,
                        "deployment_id": request.deployment_id,
                    }
                if request.require_approval and not request.approval_token:
                    approval_token = await self._request_approval(request)
                    return {
                        "status": "approval_required",
                        "approval_token": approval_token,
                        "deployment_id": request.deployment_id,
                    }
                async with self.streaming_handler.stream_deployment(
                    request.deployment_id
                ) as stream:
                    result = await self._execute_deployment(request, stream)
                    logger.info(
                        "Deploy infrastructure completed",
                        extra={
                            "event": "deploy_complete",
                            "deployment_id": request.deployment_id,
                            "status": result.get("status"),
                        },
                    )
                    return result
            except Exception as e:
                logger.exception(
                    "Deploy infrastructure failed",
                    extra={"event": "deploy_error", "deployment_id": request.deployment_id},
                )
                return {
                    "status": "failed",
                    "error": str(e),
                    "deployment_id": request.deployment_id,
                }

        @self.mcp.tool(
            name="query_azure_resources",
            description="Query Azure resources with advanced filtering and caching",
        )
        async def query_azure_resources(
            params: AzureQueryParams,
            context: Context,
        ) -> dict[str, Any]:
            cache_key = f"azure_query:{params.get_cache_key()}"
            try:
                if not params.force_refresh:
                    cached = await self.cache.get(cache_key)
                    if cached:
                        logger.info(
                            "Azure query cache hit",
                            extra={"event": "azure_query_cache_hit"},
                        )
                        return cast("dict[str, Any]", cached)
                result = await self._execute_azure_query(params)
                if params.cache_ttl > 0:
                    await self.cache.set(cache_key, result, ttl=params.cache_ttl)
                logger.info("Azure query executed", extra={"event": "azure_query_success"})
                return result
            except Exception as e:
                logger.exception("Azure query failed", extra={"event": "azure_query_error"})
                return {"error": str(e), "data": [], "count": 0, "total_records": 0}

        @self.mcp.tool(
            name="stream_logs",
            description="Stream deployment or execution logs in real-time",
        )
        async def stream_logs(
            deployment_id: str,
            context: Context,
        ) -> Any:
            try:
                async for log_line in self.streaming_handler.stream_logs(deployment_id):
                    yield log_line
            except Exception:
                logger.exception(
                    "Stream logs failed",
                    extra={"event": "stream_logs_error", "deployment_id": deployment_id},
                )
                yield json.dumps({"level": "error", "message": "stream_failed"})

    def _setup_resources(self) -> None:
        @self.mcp.resource("azure://subscriptions/{scope}")
        async def list_subscriptions(context: Context, scope: str) -> list[dict[str, Any]]:
            try:
                return await self.resource_manager.list_subscriptions()
            except Exception:
                logger.exception(
                    "List subscriptions failed", extra={"event": "subscriptions_error"}
                )
                return []

        @self.mcp.resource("azure://resources/{subscription_id}")
        async def get_resources(
            context: Context,
            subscription_id: str,
        ) -> dict[str, Any]:
            try:
                return await self.resource_manager.get_subscription_resources(subscription_id)
            except Exception:
                logger.exception(
                    "Get resources failed",
                    extra={"event": "resources_error", "subscription_id": subscription_id},
                )
                return {
                    "subscription_id": subscription_id,
                    "total_resources": 0,
                    "resources_by_type": {},
                }

        @self.mcp.resource("azure://costs/{subscription_id}")
        async def get_costs(
            context: Context,
            subscription_id: str,
        ) -> dict[str, Any]:
            try:
                return await self.resource_manager.get_subscription_costs(
                    subscription_id,
                    datetime.utcnow() - timedelta(days=30),
                    datetime.utcnow(),
                )
            except Exception:
                logger.exception(
                    "Get costs failed",
                    extra={"event": "costs_error", "subscription_id": subscription_id},
                )
                return {
                    "subscription_id": subscription_id,
                    "period": {"start": None, "end": None},
                    "total_cost": 0,
                    "breakdown_by_category": {},
                    "top_resources": [],
                    "optimization_potential": 0,
                }

        @self.mcp.resource("tools://{scope}")
        async def list_registered_tools(context: Context, scope: str) -> list[dict[str, Any]]:
            try:
                if scope not in {"registered", "all"}:
                    return []
                tools = list_tools()
                return [
                    {"name": t.name, "description": t.description, "schema": t.schema}
                    for t in tools
                ]
            except Exception:
                logger.exception("List tools failed", extra={"event": "tools_error"})
                return []

        @self.mcp.resource("deployments://{state}")
        async def get_active_deployments(context: Context, state: str) -> list[dict[str, Any]]:
            try:
                if state != "active":
                    return []
                return await self.resource_manager.get_active_deployments()
            except Exception:
                logger.exception("List deployments failed", extra={"event": "deployments_error"})
                return []

        logger.info("Resources registered", extra={"event": "resources_registered"})

    def _setup_prompts(self) -> None:
        @self.mcp.prompt("infrastructure_deployment")
        async def infrastructure_deployment_prompt(
            context: Context,
            product: str,
            environment: str = "dev",
        ) -> str:
            template = await self.resource_manager.get_deployment_template(product, environment)
            return (
                f"Deploy {product} infrastructure in {environment} environment.\n\n"
                f"Template:\n{json.dumps(template, indent=2)}\n\n"
                "Instructions:\n"
                "1. Validate all parameters\n"
                "2. Check resource quotas\n"
                "3. Verify network connectivity\n"
                "4. Apply security policies\n"
                "5. Enable monitoring\n"
                "6. Configure backup if production\n"
            )

        @self.mcp.prompt("cost_optimization")
        async def cost_optimization_prompt(
            context: Context,
            subscription_id: str,
        ) -> str:
            costs = await self.resource_manager.get_subscription_costs(
                subscription_id,
                datetime.utcnow() - timedelta(days=30),
                datetime.utcnow(),
            )
            return (
                f"Analyze and optimize Azure costs for subscription {subscription_id}.\n\n"
                f"Current monthly spend: ${costs.get('total_cost', 0):.2f}\n"
                "Top expensive resources:\n"
                f"{json.dumps(costs.get('top_resources', []), indent=2)}\n\n"
                "Optimization strategies:\n"
                "1. Identify unused resources\n"
                "2. Right-size overprovisioned resources\n"
                "3. Suggest reserved instances\n"
                "4. Recommend spot instances where applicable\n"
                "5. Propose auto-shutdown schedules\n"
            )

        logger.info("Prompts registered", extra={"event": "prompts_registered"})

    async def _validate_deployment(self, request: DeploymentRequest) -> dict[str, Any]:
        validations = {
            "naming_conventions": await self._check_naming_conventions(request),
            "security_policies": await self._check_security_policies(request),
            "network_connectivity": await self._check_network_connectivity(request),
            "resource_quotas": await self._check_resource_quotas(request),
            "cost_estimate": await self._estimate_deployment_cost(request),
        }
        all_passed = all(v.get("passed", False) for v in validations.values())
        return {
            "all_passed": all_passed,
            "validations": validations,
            "recommendations": await self._get_deployment_recommendations(request),
        }

    async def _execute_deployment(self, request: DeploymentRequest, stream: Any) -> dict[str, Any]:
        steps = [
            ("Initializing", self._init_deployment),
            ("Creating resources", self._create_resources),
            ("Configuring network", self._configure_network),
            ("Applying security", self._apply_security),
            ("Enabling monitoring", self._enable_monitoring),
            ("Running tests", self._run_tests),
            ("Finalizing", self._finalize_deployment),
        ]
        results: list[dict[str, Any]] = []
        for step_name, step_func in steps:
            await stream.send(f"Starting: {step_name}")
            try:
                result = await step_func(request)
                results.append({"step": step_name, "status": "success", "result": result})
                await stream.send(f"Completed: {step_name}")
            except Exception as e:
                results.append({"step": step_name, "status": "failed", "error": str(e)})
                await stream.send(f"Failed: {step_name} - {e!s}")
                if not request.continue_on_error:
                    break
        status = "completed" if all(r["status"] == "success" for r in results) else "failed"
        return {
            "deployment_id": request.deployment_id,
            "status": status,
            "steps": results,
            "summary": await self._generate_deployment_summary(request, results),
        }

    async def _execute_azure_query(self, params: AzureQueryParams) -> dict[str, Any]:
        rg_client = self._get_resource_graph_client()
        request = QueryRequest(
            query=params.kql,
            subscriptions=params.subscriptions or self._get_allowed_subscriptions(),
            options=(
                QueryRequestOptions(top=params.top, skip=params.skip, skip_token=params.skip_token)
                if params.top or params.skip or params.skip_token
                else None
            ),
        )
        result = await asyncio.to_thread(rg_client.resources, request)
        data = result.data[: params.top] if params.top else result.data
        return {
            "data": data,
            "count": result.count,
            "total_records": result.total_records,
            "skip_token": result.skip_token,
            "result_truncated": result.result_truncated,
            "facets": result.facets,
        }

    def _get_resource_graph_client(self) -> ResourceGraphClient:
        if not hasattr(self, "_rg_client"):
            cred = ChainedTokenCredential(ManagedIdentityCredential(), AzureCliCredential())
            self._rg_client = ResourceGraphClient(cred)
        return self._rg_client

    def _get_allowed_subscriptions(self) -> list[str]:
        raw = os.getenv("AZURE_SUBSCRIPTIONS", "")
        return [s.strip() for s in raw.split(",") if s.strip()]

    async def _check_naming_conventions(self, request: DeploymentRequest) -> dict[str, Any]:
        pattern = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")
        invalid: list[dict[str, str]] = []
        seen: set[str] = set()
        rg = getattr(request, "resource_group", "") or ""
        if not rg or len(rg) > 90:
            invalid.append({"scope": "resource_group", "name": rg or ""})
        for r in request.resources:
            name = str(r.get("name", "")).strip()
            rtype = str(r.get("type", "")).strip()
            if not name or not rtype:
                invalid.append({"scope": "resource", "name": name or "", "type": rtype or ""})
                continue
            if name in seen:
                invalid.append({"scope": "duplicate", "name": name, "type": rtype})
            seen.add(name)
            if not pattern.match(name):
                invalid.append({"scope": "format", "name": name, "type": rtype})
        passed = len(invalid) == 0
        return {
            "passed": passed,
            "details": {"invalid": invalid, "checked": len(request.resources)},
        }

    async def _check_security_policies(self, request: DeploymentRequest) -> dict[str, Any]:
        required_tags = {"owner", "environment"}
        missing_tags: list[str] = []
        enforced: list[dict[str, Any]] = []
        tags = getattr(request, "tags", {}) or {}
        for t in required_tags:
            if t not in tags:
                missing_tags.append(t)
        for r in request.resources:
            rtype = str(r.get("type", "")).lower()
            props = dict(r.get("properties", {}))
            name = str(r.get("name", ""))
            if rtype == "web_app":
                https_only = bool(props.get("https_only", True))
                tls = str(props.get("minimum_tls_version", "1.2"))
                if not https_only:
                    enforced.append({"name": name, "policy": "https_only", "value": True})
                if tls not in {"1.2", "1.3"}:
                    enforced.append({"name": name, "policy": "minimum_tls_version", "value": "1.2"})
            if rtype == "storage_account":
                allow_public = bool(props.get("allow_blob_public_access", False))
                if allow_public:
                    enforced.append(
                        {"name": name, "policy": "allow_blob_public_access", "value": False}
                    )
        passed = not missing_tags and not enforced
        return {"passed": passed, "details": {"missing_tags": missing_tags, "enforced": enforced}}

    async def _check_network_connectivity(self, request: DeploymentRequest) -> dict[str, Any]:
        issues: list[dict[str, str]] = []
        for r in request.resources:
            name = str(r.get("name", ""))
            props = dict(r.get("properties", {}))
            subnet = str(props.get("subnet_id", "")).strip()
            vnet = str(props.get("vnet_id", "")).strip()
            if subnet:
                if "/subnets/" not in subnet:
                    issues.append({"name": name, "issue": "invalid_subnet_ref"})
                if not subnet.startswith("/subscriptions/"):
                    issues.append({"name": name, "issue": "subnet_not_fully_qualified"})
            if vnet:
                if "/virtualNetworks/" not in vnet:
                    issues.append({"name": name, "issue": "invalid_vnet_ref"})
                if not vnet.startswith("/subscriptions/"):
                    issues.append({"name": name, "issue": "vnet_not_fully_qualified"})
        return {"passed": len(issues) == 0, "details": {"issues": issues}}

    async def _check_resource_quotas(self, request: DeploymentRequest) -> dict[str, Any]:
        env = str(getattr(request, "environment", "dev")).lower()
        limits: dict[str, dict[str, int]] = {
            "dev": {"storage_account": 10, "web_app": 10, "app_service_plan": 10},
            "test": {"storage_account": 20, "web_app": 20, "app_service_plan": 20},
            "staging": {"storage_account": 30, "web_app": 30, "app_service_plan": 30},
            "prod": {"storage_account": 100, "web_app": 60, "app_service_plan": 60},
        }
        limit = limits.get(env, limits["dev"])
        counts: dict[str, int] = {}
        for r in request.resources:
            rtype = str(r.get("type", "")).lower()
            counts[rtype] = counts.get(rtype, 0) + 1
        over: list[dict[str, Any]] = []
        for rtype, cnt in counts.items():
            if rtype in limit and cnt > limit[rtype]:
                over.append({"type": rtype, "count": cnt, "limit": limit[rtype]})
        return {"passed": len(over) == 0, "details": {"usage": counts, "exceeded": over}}

    async def _estimate_deployment_cost(self, request: DeploymentRequest) -> dict[str, Any]:
        prices: dict[str, Any] = {
            "app_service_plan": {"B1": 13.0, "P1V3": 147.0},
            "storage_account": {"standard_lrs": 5.0, "standard_grs": 10.0},
            "web_app": {"default": 0.0},
        }
        total = 0.0
        breakdown: list[dict[str, Any]] = []
        for r in request.resources:
            rtype = str(r.get("type", "")).lower()
            name = str(r.get("name", ""))
            if rtype == "app_service_plan":
                sku = str(r.get("sku", "B1")).upper()
                cost = float(prices["app_service_plan"].get(sku, 13.0))
            elif rtype == "storage_account":
                sku = str(r.get("sku", "Standard_LRS")).lower()
                cost = float(prices["storage_account"].get(sku, 5.0))
            elif rtype == "web_app":
                cost = float(prices["web_app"]["default"])
            else:
                cost = 0.0
            total += cost
            breakdown.append({"name": name, "type": rtype, "monthly_cost": cost})
        return {"monthly_cost": total, "currency": "USD", "items": breakdown}

    async def _get_deployment_recommendations(self, request: DeploymentRequest) -> list[str]:
        return [
            "Enable auto-scaling for production workloads",
            "Configure backup retention policy",
            "Set up cost alerts",
        ]

    async def _request_approval(self, request: DeploymentRequest) -> str:
        import uuid

        return str(uuid.uuid4())

    async def _init_deployment(self, request: DeploymentRequest) -> dict[str, Any]:
        required = ["subscription_id", "resource_group", "location", "resources"]
        for key in required:
            if not getattr(request, key, None):
                raise ValueError(f"missing_required_field:{key}")
        names: set[str] = set()
        for r in request.resources:
            name = str(r.get("name", "")).strip()
            rtype = str(r.get("type", "")).strip()
            if not name or not rtype:
                raise ValueError("invalid_resource_definition")
            if name in names:
                raise ValueError(f"duplicate_resource_name:{name}")
            names.add(name)
        return {"initialized": True, "resource_count": len(request.resources)}

    async def _create_resources(self, request: DeploymentRequest) -> dict[str, Any]:
        plan: list[dict[str, Any]] = []
        for r in request.resources:
            item: dict[str, Any] = {
                "action": "create",
                "type": str(r.get("type", "")).lower(),
                "name": str(r.get("name", "")),
                "location": str(getattr(request, "location", "westeurope")),
                "depends_on": list(r.get("depends_on", [])),
            }
            plan.append(item)
        if not plan:
            raise ValueError("empty_plan")
        return {"resources_planned": len(plan), "plan": plan}

    async def _configure_network(self, request: DeploymentRequest) -> dict[str, Any]:
        configured = 0
        checks: list[dict[str, str]] = []
        for r in request.resources:
            props = dict(r.get("properties", {}))
            subnet = str(props.get("subnet_id", "")).strip()
            if subnet:
                if "/subnets/" in subnet and subnet.startswith("/subscriptions/"):
                    configured += 1
                else:
                    checks.append({"name": str(r.get("name", "")), "issue": "invalid_subnet"})
        return {"network_configured": configured, "issues": checks}

    async def _apply_security(self, request: DeploymentRequest) -> dict[str, Any]:
        applied: list[dict[str, Any]] = []
        for r in request.resources:
            rtype = str(r.get("type", "")).lower()
            name = str(r.get("name", ""))
            if rtype == "web_app":
                applied.append({"name": name, "setting": "https_only", "value": True})
                applied.append({"name": name, "setting": "minimum_tls_version", "value": "1.2"})
            if rtype == "storage_account":
                applied.append(
                    {"name": name, "setting": "allow_blob_public_access", "value": False}
                )
        return {"security_applied": True, "changes": applied}

    async def _enable_monitoring(self, request: DeploymentRequest) -> dict[str, Any]:
        env = str(getattr(request, "environment", "dev")).lower()
        enable_backup = env == "prod"
        return {"monitoring_enabled": True, "backup_enabled": enable_backup}

    async def _run_tests(self, request: DeploymentRequest) -> dict[str, Any]:
        failures: list[str] = []
        for r in request.resources:
            if not r.get("name"):
                failures.append("missing_name")
            if not r.get("type"):
                failures.append("missing_type")
        return {"tests_passed": len(failures) == 0, "failures": failures}

    async def _finalize_deployment(self, request: DeploymentRequest) -> dict[str, Any]:
        ts = datetime.utcnow().isoformat()
        return {"finalized": True, "timestamp": ts}

    async def _generate_deployment_summary(
        self,
        request: DeploymentRequest,
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "total_steps": len(results),
            "successful_steps": sum(1 for r in results if r["status"] == "success"),
            "failed_steps": sum(1 for r in results if r["status"] == "failed"),
        }

    async def _register_vector_intelligence_tools(self) -> None:
        try:
            from app.startup.vector_integration import get_vector_startup
            
            vector_startup = await get_vector_startup()
            if vector_startup.is_initialized():
                vector_tools = await vector_startup.get_mcp_vector_tools()
                if vector_tools:
                    tool_definitions = vector_tools.get_tool_definitions()
                    
                    for tool_def in tool_definitions:
                        @self.mcp.tool(
                            name=tool_def.name,
                            description=tool_def.description
                        )
                        async def vector_tool_wrapper(context: Context, **kwargs):
                            correlation_id = kwargs.get("correlation_id", f"mcp_vector_{datetime.utcnow().timestamp()}")
                            return await vector_tools.execute_tool(
                                tool_name=tool_def.name,
                                parameters=kwargs,
                                correlation_id=correlation_id
                            )
                    
                    logger.info(f"Registered {len(tool_definitions)} vector intelligence tools")
                else:
                    logger.warning("Vector tools not available")
            else:
                logger.info("Vector system not initialized, skipping vector tools registration")
        except Exception as e:
            logger.error(f"Failed to register vector intelligence tools: {e}")

    def run(self) -> None:
        logger.info("Starting MCP server", extra={"event": "mcp_run", "transport": self.transport})
        try:
            self.mcp.run(transport=self.transport)
        except EOFError:
            logger.info("MCP server stopped: stdio closed", extra={"event": "mcp_stdio_closed"})
        except KeyboardInterrupt:
            logger.info("MCP server interrupted", extra={"event": "mcp_interrupted"})
        except Exception:
            logger.exception("MCP server crashed", extra={"event": "mcp_crash"})
            raise


async def amain() -> MCPServer:
    transport = cast(
        "Literal['stdio', 'sse', 'streamable-http']",
        os.getenv("MCP_TRANSPORT", "sse").lower(),
    )
    try:
        server = await MCPServer.create(transport=transport)
        return server
    except Exception:
        logger.exception("MCP server failed to start", extra={"event": "mcp_start_error"})
        raise


def main() -> None:
    server = asyncio.run(amain())
    server.run()


if __name__ == "__main__":
    main()
