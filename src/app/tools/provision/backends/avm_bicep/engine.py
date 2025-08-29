from __future__ import annotations

import asyncio
import json
import tempfile
import time
from collections.abc import Callable, Sequence
from collections.abc import Sequence as TypingSequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from azure.mgmt.resource.resources.models import DeploymentMode
from opentelemetry import trace

from app.core.logging import get_logger
from app.tools.azure.clients import Clients, get_clients
from .emitters import EMITTERS
from .emitters.aks import AksEmitter
from .emitters.cosmos import CosmosEmitter
from .emitters.cost_estimator import CostEstimator
from .resource_mapper import ResourceMapper
from .versions import resolve
from .writer import BicepWriter


@dataclass
class ProvisionContext:
    subscription_id: str
    resource_group: str
    location: str = "westeurope"
    name_prefix: str = "app"
    environment: str = "dev"
    tags: dict[str, str] | None = None


class Emitter(Protocol):
    def supports(self, rtype: str) -> bool: ...

    def emit(
        self,
        idx: int,
        resource: dict[str, Any],
        ctx: ProvisionContext,
        w: BicepWriter,
        mod: Callable[[str], str],
    ) -> TypingSequence[str]: ...


@dataclass
class PlanPreview:
    bicep_path: str
    parameters_path: str | None
    what_if: str | None
    rendered: str
    cost_estimate: dict[str, Any] | None
    validation_results: dict[str, Any] | None


logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class BicepAvmBackend:
    def __init__(self, avm_version_map: dict[str, str] | None = None) -> None:
        self._overrides = avm_version_map or {}
        self._mapper = ResourceMapper()
        self._cost_estimator = CostEstimator()
        self._emitters_cache: list[Emitter] = []

    async def plan(
        self, ctx: ProvisionContext, spec: dict[str, Any], dry_run: bool = True
    ) -> PlanPreview:
        with tracer.start_as_current_span("avm_backend.plan") as span:
            span.set_attributes({
                "avm.subscription_id": ctx.subscription_id,
                "avm.resource_group": ctx.resource_group,
                "avm.dry_run": dry_run,
                "avm.resources_count": len(spec.get("resources", []))
            })
            
            validation_results = self._validate_spec(spec)
            if not validation_results["valid"]:
                raise ValueError(f"Invalid specification: {validation_results['errors']}")

            rendered = self._render(ctx, spec)
            tmpdir = Path(tempfile.mkdtemp(prefix="avm_plan_"))
            bicep_path = tmpdir / "main.bicep"
            bicep_path.write_text(rendered, encoding="utf-8")

            parameters_path: str | None = None
            what_if: str | None = None
            cost_estimate: dict[str, Any] | None = None

            if dry_run:
                try:
                    clients = await get_clients(ctx.subscription_id)
                    what_if_result = await self._execute_what_if(clients, ctx, str(bicep_path))
                    what_if = self._format_what_if_result(what_if_result)
                except Exception as e:
                    logger.warning("What-if analysis failed", exc_info=True, extra={"error": str(e)})
                    what_if = f"What-if analysis failed: {e!s}"

                cost_estimate = self._cost_estimator.estimate_monthly_cost(spec)

            return PlanPreview(
                bicep_path=str(bicep_path),
                parameters_path=parameters_path,
                what_if=what_if,
                rendered=rendered,
                cost_estimate=cost_estimate,
                validation_results=validation_results,
            )

    async def apply(self, ctx: ProvisionContext, bicep_file: str) -> dict[str, Any]:
        with tracer.start_as_current_span("avm_backend.apply") as span:
            span.set_attributes({
                "avm.subscription_id": ctx.subscription_id,
                "avm.resource_group": ctx.resource_group,
                "avm.bicep_file": bicep_file
            })
            
            try:
                start_time = time.time()
                clients = await get_clients(ctx.subscription_id)
                deployment_name = f"avm-deployment-{int(time.time())}"
                
                template_content = Path(bicep_file).read_text(encoding="utf-8")
                template_json = self._compile_bicep_to_json(template_content)
                
                logger.info(
                    "Starting AVM deployment via ResourceManagementClient",
                    extra={
                        "deployment_name": deployment_name,
                        "resource_group": ctx.resource_group,
                        "subscription_id": ctx.subscription_id
                    }
                )
                
                poller = await asyncio.to_thread(
                    clients.res.deployments.begin_create_or_update,
                    ctx.resource_group,
                    deployment_name,
                    {
                        "properties": {
                            "template": template_json,
                            "mode": DeploymentMode.incremental,
                            "parameters": {}
                        }
                    }
                )
                
                result = await asyncio.to_thread(poller.result)
                duration_seconds = time.time() - start_time
                
                if result and hasattr(result, 'properties') and result.properties.provisioning_state == "Succeeded":
                    logger.info(
                        "AVM deployment succeeded",
                        extra={
                            "deployment_name": deployment_name,
                            "duration_seconds": duration_seconds,
                            "deployment_id": getattr(result, 'id', '')
                        }
                    )
                    return {
                        "status": "succeeded",
                        "deployment_id": getattr(result, 'id', ''),
                        "outputs": getattr(result.properties, 'outputs', {}) if hasattr(result, 'properties') else {},
                        "duration": f"{duration_seconds:.1f}s",
                    }
                
                logger.error(
                    "AVM deployment failed",
                    extra={
                        "deployment_name": deployment_name,
                        "provisioning_state": getattr(result.properties, 'provisioning_state', 'Unknown') if hasattr(result, 'properties') else 'Unknown'
                    }
                )
                return {
                    "status": "failed", 
                    "message": getattr(result.properties, 'status_message', 'Deployment failed') if hasattr(result, 'properties') else 'Deployment failed'
                }
                
            except Exception as e:
                logger.error("AVM deployment error", exc_info=True, extra={"error": str(e)})
                return {"status": "error", "message": str(e)}

    async def plan_from_nlu(
        self, nlu_result: dict[str, Any], ctx: ProvisionContext, dry_run: bool = True
    ) -> PlanPreview:
        spec = self._mapper.map_nlu_to_avm(nlu_result)

        if not spec.get("resources"):
            spec = {"resources": [spec]}

        return await self.plan(ctx, spec, dry_run)

    def _render(self, ctx: ProvisionContext, spec: dict[str, Any]) -> str:
        w = BicepWriter()

        w.line("@description('The location for all resources')")
        w.line(f"param location string = '{ctx.location}'")
        w.line("")

        if self._requires_log_analytics(spec):
            w.line("@description('Log Analytics Workspace ID for monitoring')")
            w.line("param logAnalyticsWorkspaceId string = ''")
            w.line("")

        tags = {"environment": ctx.environment, "managedBy": "avm-bicep", **(ctx.tags or {})}
        w.line("var tags = " + w.obj(tags))
        w.line(f"var namePrefix = '{ctx.name_prefix}'")
        w.line(f"var environment = '{ctx.environment}'")
        w.line("")

        resource_graph = self._build_dependency_graph(spec.get("resources", []))
        ordered_resources = self._topological_sort(resource_graph)

        emitted_resources: dict[str, int] = {}

        for idx, resource_id in enumerate(ordered_resources, start=1):
            resource = next(
                (r for r in spec.get("resources", []) if self._get_resource_id(r) == resource_id),
                None,
            )
            if not resource:
                continue

            rtype = resource.get("type")
            emitted = False

            for emitter in self._emitters():
                if emitter.supports(rtype):
                    lines = emitter.emit(idx, resource, ctx, w, self._mod)
                    w.extend(lines)
                    emitted_resources[resource_id] = idx
                    emitted = True
                    break

            if not emitted:
                raise ValueError(f"Unsupported resource type: {rtype}")

        self._add_outputs(w, spec.get("resources", []), emitted_resources)
        return w.render()

    def _emitters(self) -> Sequence[Emitter]:
        if not self._emitters_cache:
            base_emitters: list[Emitter] = list(cast("Sequence[Emitter]", EMITTERS))
            base_emitters.extend([CosmosEmitter(), AksEmitter()])
            self._emitters_cache = base_emitters
        return self._emitters_cache

    def _mod(self, ref: str) -> str:
        return resolve(ref, self._overrides)

    def _validate_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []

        resources = spec.get("resources", [])
        if not resources:
            errors.append("No resources defined")

        resource_names: set[str] = set()
        for resource in resources:
            if not resource.get("type"):
                errors.append(f"Resource missing type: {resource}")

            name = resource.get("name")
            if not name:
                errors.append(f"Resource missing name: {resource}")
            elif name in resource_names:
                errors.append(f"Duplicate resource name: {name}")
            else:
                resource_names.add(name)

            if not self._is_supported_resource_type(resource.get("type")):
                warnings.append(f"Unknown resource type: {resource.get('type')}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    def _is_supported_resource_type(self, rtype: str | None) -> bool:
        if not rtype:
            return False
        for emitter in self._emitters():
            if emitter.supports(rtype):
                return True
        return False

    def _requires_log_analytics(self, spec: dict[str, Any]) -> bool:
        for resource in spec.get("resources", []):
            rtype = resource.get("type")
            if rtype in ["aks_cluster", "app_insights"]:
                return True
            if rtype == "web_stack" and resource.get("site", {}).get("enable_monitoring"):
                return True
        return False

    def _build_dependency_graph(self, resources: list[dict[str, Any]]) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {}
        for resource in resources:
            resource_id = self._get_resource_id(resource)
            dependencies = resource.get("depends_on", [])
            graph[resource_id] = dependencies
        return graph

    def _get_resource_id(self, resource: dict[str, Any]) -> str:
        return f"{resource.get('type', 'unknown')}_{resource.get('name', 'unnamed')}"

    def _topological_sort(self, graph: dict[str, list[str]]) -> list[str]:
        visited: set[str] = set()
        stack: list[str] = []

        def visit(node: str) -> None:
            if node in visited:
                return
            visited.add(node)
            for dep in graph.get(node, []):
                if dep in graph:
                    visit(dep)
            stack.append(node)

        for node in graph:
            visit(node)
        return stack

    async def _execute_what_if(self, clients: Clients, ctx: ProvisionContext, bicep_file: str) -> Any:
        deployment_name = f"avm-what-if-{int(time.time())}"
        template_content = Path(bicep_file).read_text(encoding="utf-8")
        template_json = self._compile_bicep_to_json(template_content)
        
        poller = await asyncio.to_thread(
            clients.res.deployments.begin_what_if,
            ctx.resource_group,
            deployment_name,
            {
                "properties": {
                    "template": template_json,
                    "mode": DeploymentMode.incremental,
                    "parameters": {}
                }
            }
        )
        
        return await asyncio.to_thread(poller.result)

    def _format_what_if_result(self, result: Any) -> str:
        if not result:
            return "What-if analysis completed with no changes"
        
        changes = []
        for change in getattr(result, "changes", []) or []:
            change_type = getattr(change, "change_type", "Unknown")
            resource_id = getattr(change, "resource_id", "Unknown resource")
            changes.append(f"  {change_type}: {resource_id}")
        
        if not changes:
            return "What-if analysis completed with no changes"
        
        return "What-if analysis results:\n" + "\n".join(changes)

    def _add_outputs(self, w: BicepWriter, resources: list[dict[str, Any]], emitted_resources: dict[str, int]) -> None:
        """Add output definitions for deployed resources."""
        if not resources:
            return
            
        w.line("")
        w.line("// Outputs")
        
        for resource in resources:
            resource_type = resource.get("type")
            resource_name = resource.get("name", "resource")
            resource_id = self._get_resource_id(resource)
            
            if resource_id not in emitted_resources:
                continue
                
            idx = emitted_resources[resource_id]
            
            if resource_type == "web_stack":
                w.line(f"output webapp_{idx}_id string = site_{idx}.outputs.resourceId")
                w.line(f"output webapp_{idx}_name string = site_{idx}.outputs.name")
                w.line(f"output webapp_{idx}_hostname string = site_{idx}.outputs.defaultHostname")
                w.line(f"output webapp_{idx}_plan_id string = plan_{idx}.id")
                
            elif resource_type == "storage_account":
                w.line(f"output storage_{idx}_id string = sa_{idx}.outputs.resourceId")
                w.line(f"output storage_{idx}_name string = sa_{idx}.outputs.name")
                w.line(f"output storage_{idx}_primary_blob_endpoint string = sa_{idx}.outputs.primaryBlobEndpoint")
                
            elif resource_type == "aks_cluster":
                w.line(f"output aks_{idx}_id string = aks_{idx}.outputs.resourceId")
                w.line(f"output aks_{idx}_name string = aks_{idx}.outputs.name")
                w.line(f"output aks_{idx}_fqdn string = aks_{idx}.outputs.controlPlaneFQDN")
                
            elif resource_type == "key_vault":
                w.line(f"output keyvault_{idx}_id string = kv_{idx}.outputs.resourceId")
                w.line(f"output keyvault_{idx}_name string = kv_{idx}.outputs.name")
                w.line(f"output keyvault_{idx}_uri string = kv_{idx}.outputs.uri")
                
            elif resource_type == "sql_server":
                w.line(f"output sqlserver_{idx}_id string = sqlsrv_{idx}.id")
                w.line(f"output sqlserver_{idx}_name string = sqlsrv_{idx}.name")
                w.line(f"output sqlserver_{idx}_fqdn string = sqlsrv_{idx}.properties.fullyQualifiedDomainName")
                
            elif resource_type == "cosmos_account":
                w.line(f"output cosmos_{idx}_id string = cosmos_{idx}.id")
                w.line(f"output cosmos_{idx}_name string = cosmos_{idx}.name")
                w.line(f"output cosmos_{idx}_endpoint string = cosmos_{idx}.properties.documentEndpoint")
                
            elif resource_type == "vnet":
                w.line(f"output vnet_{idx}_id string = vnet_{idx}.outputs.resourceId")
                w.line(f"output vnet_{idx}_name string = vnet_{idx}.outputs.name")
                
            else:
                # Generic output for unknown resource types
                safe_name = resource_type.replace("-", "_").replace(".", "_")
                w.line(f"output {safe_name}_{idx}_id string = '{resource_name} deployed'")
                w.line(f"output {safe_name}_{idx}_name string = '{resource_name}'")

    def _compile_bicep_to_json(self, bicep_content: str) -> dict[str, Any]:
        try:
            import subprocess
            import tempfile
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.bicep', delete=False) as f:
                f.write(bicep_content)
                bicep_path = f.name
            
            result = subprocess.run(
                ['az', 'bicep', 'build', '--file', bicep_path, '--stdout'],
                capture_output=True,
                text=True,
                check=True
            )
            
            Path(bicep_path).unlink()
            return json.loads(result.stdout)
            
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Bicep compilation failed, using template as-is: {e}")
            try:
                return json.loads(bicep_content)
            except json.JSONDecodeError:
                return {
                    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
                    "contentVersion": "1.0.0.0",
                    "resources": [],
                    "outputs": {}
                }
