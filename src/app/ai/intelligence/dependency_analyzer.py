from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace

from app.core.logging import get_logger
from app.observability.agent_tracing import get_agent_tracer

logger = get_logger(__name__)
tracer = get_agent_tracer("DependencyAnalyzer")


@dataclass
class ResourceDependency:
    resource_name: str
    resource_type: str
    depends_on: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    deployment_group: int = 0
    can_deploy_parallel: bool = True
    estimated_deploy_time_seconds: int = 60


@dataclass
class DeploymentPlan:
    deployment_groups: list[list[ResourceDependency]]
    total_estimated_time_seconds: int
    parallel_opportunities: int
    critical_path: list[str]
    dependency_warnings: list[str] = field(default_factory=list)


class DependencyAnalyzer:
    def __init__(self) -> None:
        self._resource_templates = self._initialize_resource_templates()

    def _initialize_resource_templates(self) -> dict[str, dict[str, Any]]:
        return {
            "webapp": {
                "requires": ["resource_group", "app_service_plan"],
                "provides": ["web_endpoint", "app_identity"],
                "deploy_time": 120,
                "parallel_safe": True,
            },
            "app_service_plan": {
                "requires": ["resource_group"],
                "provides": ["compute_capacity"],
                "deploy_time": 90,
                "parallel_safe": True,
            },
            "aks_cluster": {
                "requires": ["resource_group", "vnet", "subnet", "log_analytics_workspace"],
                "provides": ["kubernetes_api", "node_pools"],
                "deploy_time": 600,
                "parallel_safe": False,
            },
            "vnet": {
                "requires": ["resource_group"],
                "provides": ["network_space"],
                "deploy_time": 60,
                "parallel_safe": True,
            },
            "subnet": {
                "requires": ["vnet"],
                "provides": ["network_segment"],
                "deploy_time": 30,
                "parallel_safe": True,
            },
            "log_analytics_workspace": {
                "requires": ["resource_group"],
                "provides": ["logging_sink", "monitoring_data"],
                "deploy_time": 90,
                "parallel_safe": True,
            },
            "storage_account": {
                "requires": ["resource_group"],
                "provides": ["blob_storage", "file_shares"],
                "deploy_time": 60,
                "parallel_safe": True,
            },
            "key_vault": {
                "requires": ["resource_group"],
                "provides": ["secret_store", "certificate_store"],
                "deploy_time": 90,
                "parallel_safe": True,
            },
            "sql_server": {
                "requires": ["resource_group"],
                "provides": ["database_server"],
                "deploy_time": 180,
                "parallel_safe": True,
            },
            "sql_database": {
                "requires": ["sql_server"],
                "provides": ["database_instance"],
                "deploy_time": 120,
                "parallel_safe": False,
            },
            "resource_group": {
                "requires": [],
                "provides": ["resource_container"],
                "deploy_time": 30,
                "parallel_safe": True,
            },
        }

    async def analyze_dependencies(
        self, resources: list[dict[str, Any]], environment: str = "dev"
    ) -> DeploymentPlan:
        async with tracer.trace_operation(
            "analyze_dependencies",
            {
                "resource_count": len(resources),
                "environment": environment,
                "operation.type": "analysis_start"
            }
        ) as span:
            logger.info(
                "Starting dependency analysis",
                resource_count=len(resources),
                environment=environment,
            )

            resource_deps = await self._build_dependency_graph(resources, environment)
            span.set_attributes({"dependencies_inferred": len(resource_deps)})

            deployment_groups = self._calculate_deployment_groups(resource_deps)
            span.set_attributes({"deployment_groups": len(deployment_groups)})

            critical_path = self._find_critical_path(resource_deps)
            total_time = self._estimate_total_time(deployment_groups)
            parallel_ops = sum(len(group) for group in deployment_groups if len(group) > 1)

            warnings = self._validate_dependencies(resource_deps)
            span.set_attributes({"dependency_warnings": len(warnings)})

            plan = DeploymentPlan(
                deployment_groups=deployment_groups,
                total_estimated_time_seconds=total_time,
                parallel_opportunities=parallel_ops,
                critical_path=critical_path,
                dependency_warnings=warnings,
            )

            logger.info(
                "Dependency analysis completed",
                deployment_groups=len(deployment_groups),
                estimated_time_seconds=total_time,
                parallel_opportunities=parallel_ops,
                warnings_count=len(warnings),
            )
            
            tracer.track_agent_metrics(
                "dependency_analysis",
                float(total_time * 1000),
                True,
                len(deployment_groups)
            )

            return plan

    async def _build_dependency_graph(
        self, resources: list[dict[str, Any]], environment: str
    ) -> list[ResourceDependency]:
        resource_deps: list[ResourceDependency] = []

        for resource in resources:
            resource_type = resource.get("type", "").lower().replace("microsoft.web/sites", "webapp")
            resource_name = resource.get("name", f"unnamed_{resource_type}")

            template = self._resource_templates.get(resource_type, {})
            explicit_deps = resource.get("depends_on", [])

            inferred_deps = await self._infer_dependencies(resource, resources, environment)
            all_deps = list(set(explicit_deps + inferred_deps))

            dep = ResourceDependency(
                resource_name=resource_name,
                resource_type=resource_type,
                depends_on=all_deps,
                provides=template.get("provides", []),
                can_deploy_parallel=template.get("parallel_safe", True),
                estimated_deploy_time_seconds=template.get("deploy_time", 60),
            )
            resource_deps.append(dep)

            logger.debug(
                "Resource dependency built",
                resource_name=resource_name,
                resource_type=resource_type,
                dependencies_count=len(all_deps),
                inferred_dependencies=len(inferred_deps),
            )

        return resource_deps

    async def _infer_dependencies(
        self, resource: dict[str, Any], all_resources: list[dict[str, Any]], environment: str
    ) -> list[str]:
        resource_type = resource.get("type", "").lower()
        inferred: list[str] = []

        resource_names = {r.get("name", "") for r in all_resources}

        if resource_type in ["microsoft.web/sites", "webapp"]:
            required_plan = f"{resource.get('name', 'app')}-plan"
            if required_plan in resource_names or any("serverfarm" in r.get("type", "") for r in all_resources):
                plan_name = next(
                    (
                        r.get("name", required_plan)
                        for r in all_resources
                        if "serverfarm" in r.get("type", "")
                    ),
                    required_plan,
                )
                inferred.append(plan_name)

        elif resource_type in ["microsoft.containerservice/managedclusters", "aks_cluster"]:
            if any("network/virtualnetworks" in r.get("type", "") for r in all_resources):
                vnet_name = next(
                    r.get("name") for r in all_resources if "virtualnetworks" in r.get("type", "")
                )
                if vnet_name:
                    inferred.append(vnet_name)

            if any("operationalinsights/workspaces" in r.get("type", "") for r in all_resources):
                workspace_name = next(
                    r.get("name") for r in all_resources if "workspaces" in r.get("type", "")
                )
                if workspace_name:
                    inferred.append(workspace_name)

        elif resource_type in ["microsoft.network/virtualnetworks/subnets", "subnet"]:
            parent_vnet = resource.get("vnet_name")
            if parent_vnet and parent_vnet in resource_names:
                inferred.append(parent_vnet)

        elif resource_type in ["microsoft.sql/servers/databases", "sql_database"]:
            parent_server = resource.get("server_name")
            if parent_server and parent_server in resource_names:
                inferred.append(parent_server)

        return inferred

    def _calculate_deployment_groups(
        self, resource_deps: list[ResourceDependency]
    ) -> list[list[ResourceDependency]]:
        name_to_resource = {r.resource_name: r for r in resource_deps}
        groups: list[list[ResourceDependency]] = []
        deployed: set[str] = set()

        while len(deployed) < len(resource_deps):
            current_group: list[ResourceDependency] = []

            for resource in resource_deps:
                if resource.resource_name in deployed:
                    continue

                deps_satisfied = all(dep in deployed for dep in resource.depends_on)

                if deps_satisfied:
                    current_group.append(resource)
                    deployed.add(resource.resource_name)

            if not current_group:
                remaining = [r for r in resource_deps if r.resource_name not in deployed]
                logger.warning(
                    "Circular dependency detected or unresolved dependencies",
                    remaining_resources=[r.resource_name for r in remaining],
                )
                current_group = remaining[:1]
                if current_group:
                    deployed.add(current_group[0].resource_name)

            if current_group:
                groups.append(current_group)

        for i, group in enumerate(groups):
            for resource in group:
                resource.deployment_group = i

        return groups

    def _find_critical_path(self, resource_deps: list[ResourceDependency]) -> list[str]:
        name_to_resource = {r.resource_name: r for r in resource_deps}
        longest_path: list[str] = []
        max_time = 0

        def calculate_path_time(resource_name: str, visited: set[str]) -> tuple[int, list[str]]:
            if resource_name in visited:
                return 0, []

            resource = name_to_resource.get(resource_name)
            if not resource:
                return 0, []

            visited.add(resource_name)
            max_dep_time = 0
            max_dep_path: list[str] = []

            for dep in resource.depends_on:
                dep_time, dep_path = calculate_path_time(dep, visited.copy())
                if dep_time > max_dep_time:
                    max_dep_time = dep_time
                    max_dep_path = dep_path

            visited.remove(resource_name)
            total_time = max_dep_time + resource.estimated_deploy_time_seconds
            full_path = max_dep_path + [resource_name]
            return total_time, full_path

        for resource in resource_deps:
            time, path = calculate_path_time(resource.resource_name, set())
            if time > max_time:
                max_time = time
                longest_path = path

        return longest_path

    def _estimate_total_time(self, deployment_groups: list[list[ResourceDependency]]) -> int:
        total_time = 0
        for group in deployment_groups:
            if group:
                group_time = max(r.estimated_deploy_time_seconds for r in group)
                total_time += group_time
        return total_time

    def _validate_dependencies(self, resource_deps: list[ResourceDependency]) -> list[str]:
        warnings: list[str] = []
        resource_names = {r.resource_name for r in resource_deps}

        for resource in resource_deps:
            for dep in resource.depends_on:
                if dep not in resource_names:
                    warning = f"Resource '{resource.resource_name}' depends on '{dep}' which is not in deployment"
                    warnings.append(warning)

            if resource.resource_type == "aks_cluster" and not any(
                dep for dep in resource_deps if dep.resource_type == "log_analytics_workspace"
            ):
                warnings.append(
                    f"AKS cluster '{resource.resource_name}' should have Log Analytics workspace for monitoring"
                )

        return warnings

    async def optimize_for_parallel_deployment(
        self, plan: DeploymentPlan
    ) -> tuple[DeploymentPlan, dict[str, Any]]:
        async with tracer.trace_operation(
            "optimize_parallel_deployment",
            {
                "original_groups": len(plan.deployment_groups),
                "original_time_seconds": plan.total_estimated_time_seconds,
                "operation.type": "optimization_start"
            }
        ) as span:
            optimizations: dict[str, Any] = {}
            original_time = plan.total_estimated_time_seconds

            optimized_groups: list[list[ResourceDependency]] = []
            for group in plan.deployment_groups:
                if len(group) <= 1:
                    optimized_groups.append(group)
                    continue

                parallel_safe = [r for r in group if r.can_deploy_parallel]
                sequential_only = [r for r in group if not r.can_deploy_parallel]

                if parallel_safe and sequential_only:
                    optimized_groups.append(parallel_safe)
                    for seq_resource in sequential_only:
                        optimized_groups.append([seq_resource])
                else:
                    optimized_groups.append(group)

            new_total_time = self._estimate_total_time(optimized_groups)
            time_saved = original_time - new_total_time
            parallel_ops = sum(len(group) for group in optimized_groups if len(group) > 1)

            optimizations = {
                "original_time_seconds": original_time,
                "optimized_time_seconds": new_total_time,
                "time_saved_seconds": time_saved,
                "parallel_operations": parallel_ops,
                "optimization_applied": time_saved > 0,
            }

            optimized_plan = DeploymentPlan(
                deployment_groups=optimized_groups,
                total_estimated_time_seconds=new_total_time,
                parallel_opportunities=parallel_ops,
                critical_path=plan.critical_path,
                dependency_warnings=plan.dependency_warnings,
            )

            logger.info(
                "Parallel deployment optimization completed",
                time_saved_seconds=time_saved,
                parallel_opportunities=parallel_ops,
                optimization_effective=time_saved > 0,
            )

            span.set_attributes(optimizations)
            return optimized_plan, optimizations