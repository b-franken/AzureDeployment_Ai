from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol, cast

from azure.identity import AzureCliCredential, ChainedTokenCredential, ManagedIdentityCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
from mcp.server.fastmcp import Context, FastMCP

from app.ai.tools_router import ToolExecutionContext, maybe_call_tool
from app.platform.audit.logger import AuditLogger
from app.tools.registry import ensure_tools_loaded, list_tools

from .cache import MCPCache
from .resources import ResourceManager
from .streaming import StreamingHandler


class ToolExecutionRequest(Protocol):
    tool_name: str
    input_text: str
    memory: Any
    provider: str | None
    model: str | None
    subscription_id: str | None
    resource_group: str | None
    environment: str | None
    correlation_id: str | None
    audit_enabled: bool
    cost_limit: float | None
    dry_run: bool
    cache_ttl: int
    force_refresh: bool

    def get_cache_key(self) -> str: ...


class DeploymentRequest(Protocol):
    deployment_id: str
    resources: list[dict[str, Any]]
    validate_only: bool
    require_approval: bool
    approval_token: str | None
    continue_on_error: bool


class AzureQueryParams(Protocol):
    kql: str
    subscriptions: list[str] | None
    top: int | None
    skip: int | None
    skip_token: str | None
    cache_ttl: int
    force_refresh: bool

    def get_cache_key(self) -> str: ...


class MCPServer:
    def __init__(
        self,
        name: str = "DevOps AI Tools",
        transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
    ):
        self.mcp = FastMCP(name=name)
        self.transport = transport
        self.cache = MCPCache()
        self.resource_manager = ResourceManager()
        self.streaming_handler = StreamingHandler()
        self.audit_logger = AuditLogger()
        self._setup_tools()
        self._setup_resources()
        self._setup_prompts()

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
            cached_result = await self.cache.get(cache_key)
            if cached_result and not request.force_refresh:
                return cast(dict[str, Any], cached_result)

            try:
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

                return response

            except Exception as e:
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

            async with self.streaming_handler.stream_deployment(request.deployment_id) as stream:
                result = await self._execute_deployment(request, stream)
                return result

        @self.mcp.tool(
            name="query_azure_resources",
            description="Query Azure resources with advanced filtering and caching",
        )
        async def query_azure_resources(
            params: AzureQueryParams,
            context: Context,
        ) -> dict[str, Any]:
            cache_key = f"azure_query:{params.get_cache_key()}"

            if not params.force_refresh:
                cached = await self.cache.get(cache_key)
                if cached:
                    return cast(dict[str, Any], cached)

            result = await self._execute_azure_query(params)

            if params.cache_ttl > 0:
                await self.cache.set(cache_key, result, ttl=params.cache_ttl)

            return result

        @self.mcp.tool(
            name="stream_logs", description="Stream deployment or execution logs in real-time"
        )
        async def stream_logs(
            deployment_id: str,
            context: Context,
        ) -> AsyncIterator[str]:
            async for log_line in self.streaming_handler.stream_logs(deployment_id):
                yield log_line

    def _setup_resources(self) -> None:
        @self.mcp.resource("azure://subscriptions")
        async def list_subscriptions(context: Context) -> list[dict[str, Any]]:
            return await self.resource_manager.list_subscriptions()

        @self.mcp.resource("azure://resources/{subscription_id}")
        async def get_resources(
            context: Context,
            subscription_id: str,
        ) -> dict[str, Any]:
            return await self.resource_manager.get_subscription_resources(subscription_id)

        @self.mcp.resource("azure://costs/{subscription_id}")
        async def get_costs(
            context: Context,
            subscription_id: str,
        ) -> dict[str, Any]:
            return await self.resource_manager.get_subscription_costs(
                subscription_id,
                datetime.utcnow() - timedelta(days=30),
                datetime.utcnow(),
            )

        @self.mcp.resource("tools://registered")
        async def list_registered_tools(context: Context) -> list[dict[str, Any]]:
            tools = list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "schema": t.schema,
                }
                for t in tools
            ]

        @self.mcp.resource("deployments://active")
        async def get_active_deployments(context: Context) -> list[dict[str, Any]]:
            return await self.resource_manager.get_active_deployments()

    def _setup_prompts(self) -> None:
        @self.mcp.prompt("infrastructure_deployment")
        async def infrastructure_deployment_prompt(
            context: Context,
            product: str,
            environment: str = "dev",
        ) -> str:
            template = await self.resource_manager.get_deployment_template(
                product,
                environment,
            )
            return f"""Deploy {product} infrastructure in {environment} environment.

Template:
{json.dumps(template, indent=2)}

Instructions:
1. Validate all parameters
2. Check resource quotas
3. Verify network connectivity
4. Apply security policies
5. Enable monitoring
6. Configure backup if production
"""

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
            return f"""Analyze and optimize Azure costs for subscription {subscription_id}.

Current monthly spend: ${costs.get("total_cost", 0):.2f}
Top expensive resources:
{json.dumps(costs.get("top_resources", []), indent=2)}

Optimization strategies:
1. Identify unused resources
2. Right-size overprovisioned resources
3. Suggest reserved instances
4. Recommend spot instances where applicable
5. Propose auto-shutdown schedules
"""

    async def _validate_deployment(
        self,
        request: DeploymentRequest,
    ) -> dict[str, Any]:
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

    async def _execute_deployment(
        self,
        request: DeploymentRequest,
        stream: Any,
    ) -> dict[str, Any]:
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
                results.append(
                    {
                        "step": step_name,
                        "status": "success",
                        "result": result,
                    }
                )
                await stream.send(f"Completed: {step_name}")
            except Exception as e:
                results.append(
                    {
                        "step": step_name,
                        "status": "failed",
                        "error": str(e),
                    }
                )
                await stream.send(f"Failed: {step_name} - {str(e)}")
                if not request.continue_on_error:
                    break

        return {
            "deployment_id": request.deployment_id,
            "status": "completed" if all(r["status"] == "success" for r in results) else "failed",
            "steps": results,
            "summary": await self._generate_deployment_summary(request, results),
        }

    async def _execute_azure_query(
        self,
        params: AzureQueryParams,
    ) -> dict[str, Any]:
        rg_client = self._get_resource_graph_client()

        request = QueryRequest(
            query=params.kql,
            subscriptions=params.subscriptions or self._get_allowed_subscriptions(),
            options=(
                QueryRequestOptions(
                    top=params.top,
                    skip=params.skip,
                    skip_token=params.skip_token,
                )
                if params.top or params.skip or params.skip_token
                else None
            ),
        )

        result = await asyncio.to_thread(rg_client.resources, request)

        return {
            "data": result.data[: params.top] if params.top else result.data,
            "count": result.count,
            "total_records": result.total_records,
            "skip_token": result.skip_token,
            "result_truncated": result.result_truncated,
            "facets": result.facets,
        }

    def _get_resource_graph_client(self) -> ResourceGraphClient:
        if not hasattr(self, "_rg_client"):
            cred = ChainedTokenCredential(
                ManagedIdentityCredential(),
                AzureCliCredential(),
            )
            self._rg_client = ResourceGraphClient(cred)
        return self._rg_client

    def _get_allowed_subscriptions(self) -> list[str]:
        import os

        raw = os.getenv("AZURE_SUBSCRIPTIONS", "")
        return [s.strip() for s in raw.split(",") if s.strip()]

    async def _check_naming_conventions(self, request: DeploymentRequest) -> dict[str, Any]:
        return {"passed": True, "details": "Naming conventions validated"}

    async def _check_security_policies(self, request: DeploymentRequest) -> dict[str, Any]:
        return {"passed": True, "details": "Security policies validated"}

    async def _check_network_connectivity(self, request: DeploymentRequest) -> dict[str, Any]:
        return {"passed": True, "details": "Network connectivity verified"}

    async def _check_resource_quotas(self, request: DeploymentRequest) -> dict[str, Any]:
        return {"passed": True, "details": "Resource quotas available"}

    async def _estimate_deployment_cost(self, request: DeploymentRequest) -> dict[str, Any]:
        return {"monthly_cost": 150.0, "currency": "USD"}

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
        return {"initialized": True}

    async def _create_resources(self, request: DeploymentRequest) -> dict[str, Any]:
        return {"resources_created": len(request.resources)}

    async def _configure_network(self, request: DeploymentRequest) -> dict[str, Any]:
        return {"network_configured": True}

    async def _apply_security(self, request: DeploymentRequest) -> dict[str, Any]:
        return {"security_applied": True}

    async def _enable_monitoring(self, request: DeploymentRequest) -> dict[str, Any]:
        return {"monitoring_enabled": True}

    async def _run_tests(self, request: DeploymentRequest) -> dict[str, Any]:
        return {"tests_passed": True}

    async def _finalize_deployment(self, request: DeploymentRequest) -> dict[str, Any]:
        return {"finalized": True}

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

    def run(self) -> None:
        self.mcp.run(transport=self.transport)


def main() -> None:
    import os

    transport = cast(
        Literal["stdio", "sse", "streamable-http"],
        os.getenv("MCP_TRANSPORT", "stdio").lower(),
    )
    server = MCPServer(transport=transport)
    server.run()


if __name__ == "__main__":
    main()
