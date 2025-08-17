from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Sequence
from collections.abc import Sequence as TypingSequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from emitters.cost_estimator import CostEstimator

from .az_cli import AzCli
from .emitters import EMITTERS
from .emitters.aks import AksEmitter
from .emitters.cosmos import CosmosEmitter
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


class BicepAvmBackend:
    def __init__(self, avm_version_map: dict[str, str] | None = None) -> None:
        self._az = AzCli()
        self._overrides = avm_version_map or {}
        self._mapper = ResourceMapper()
        self._cost_estimator = CostEstimator()
        self._emitters_cache: list[Emitter] = []

    async def plan(
        self, ctx: ProvisionContext, spec: dict[str, Any], dry_run: bool = True
    ) -> PlanPreview:
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
                what_if = await self._az.what_if_group(
                    ctx.resource_group, str(bicep_path), ctx.subscription_id
                )
            except Exception as e:
                what_if = f"What-if analysis failed: {str(e)}"

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
        try:
            out = await self._az.deploy_group(ctx.resource_group, bicep_file, ctx.subscription_id)
            result = json.loads(out) if isinstance(out, str) else out

            if (
                isinstance(result, dict)
                and result.get("properties", {}).get("provisioningState") == "Succeeded"
            ):
                return {
                    "status": "succeeded",
                    "deployment_id": result.get("id", ""),
                    "outputs": result.get("properties", {}).get("outputs", {}),
                    "duration": result.get("properties", {}).get("duration", ""),
                }

            return {"status": "failed", "raw": result}
        except Exception as e:
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

        return w.render()

    def _emitters(self) -> Sequence[Emitter]:
        if not self._emitters_cache:
            base_emitters: list[Emitter] = list(cast(Sequence[Emitter], EMITTERS))
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
