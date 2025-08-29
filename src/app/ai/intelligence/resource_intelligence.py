from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace

from app.core.logging import get_logger
from app.observability.agent_tracing import get_agent_tracer

logger = get_logger(__name__)
tracer = get_agent_tracer("ResourceIntelligence")


@dataclass
class ResourceRecommendation:
    resource_type: str
    resource_name: str
    reason: str
    priority: str
    configuration: dict[str, Any] = field(default_factory=dict)
    estimated_cost_impact: str = "unknown"


@dataclass
class ResourceIntelligenceResult:
    inferred_resources: list[dict[str, Any]]
    recommendations: list[ResourceRecommendation]
    warnings: list[str]
    configuration_adjustments: dict[str, Any] = field(default_factory=dict)


class ResourceIntelligence:
    def __init__(self) -> None:
        self._resource_patterns = self._initialize_resource_patterns()
        self._complementary_resources = self._initialize_complementary_resources()

    def _initialize_resource_patterns(self) -> dict[str, dict[str, Any]]:
        return {
            "webapp": {
                "requires_plan": True,
                "default_runtime": "dotnet",
                "monitoring_recommended": True,
                "scaling_patterns": ["basic", "standard", "premium"],
            },
            "aks_cluster": {
                "requires_vnet": True,
                "requires_monitoring": True,
                "node_pools": {"min": 1, "max": 10, "default": 3},
                "vm_sizes": ["Standard_D2s_v3", "Standard_D4s_v3"],
            },
            "sql_server": {
                "firewall_required": True,
                "backup_recommended": True,
                "geo_replication": {"prod": True, "dev": False},
            },
        }

    def _initialize_complementary_resources(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "webapp": [
                {
                    "type": "application_insights",
                    "reason": "Application monitoring and diagnostics",
                    "priority": "high",
                    "configuration": {"sampling_percentage": 100},
                },
                {
                    "type": "key_vault",
                    "reason": "Secure configuration and secrets management",
                    "priority": "medium",
                    "configuration": {"sku": "standard"},
                },
            ],
            "aks_cluster": [
                {
                    "type": "container_registry",
                    "reason": "Private container image storage",
                    "priority": "high",
                    "configuration": {"sku": "Basic"},
                },
                {
                    "type": "log_analytics_workspace",
                    "reason": "Centralized logging and monitoring",
                    "priority": "high",
                    "configuration": {"retention_days": 30},
                },
                {
                    "type": "key_vault",
                    "reason": "Kubernetes secrets and certificate management",
                    "priority": "medium",
                    "configuration": {"sku": "standard"},
                },
            ],
            "sql_server": [
                {
                    "type": "storage_account",
                    "reason": "Database backup storage",
                    "priority": "medium",
                    "configuration": {"tier": "Standard", "replication": "LRS"},
                },
                {
                    "type": "key_vault",
                    "reason": "Database connection string and credential storage",
                    "priority": "high",
                    "configuration": {"sku": "standard"},
                },
            ],
        }

    async def analyze_resource_requirements(
        self, primary_resource: dict[str, Any], environment: str = "dev", user_preferences: dict[str, Any] | None = None
    ) -> ResourceIntelligenceResult:
        preferences = user_preferences or {}
        
        async with tracer.trace_operation(
            "analyze_resource_requirements",
            {
                "resource_type": primary_resource.get("type", "unknown"),
                "resource_name": primary_resource.get("name", "unnamed"),
                "environment": environment,
                "operation.type": "analysis_start"
            }
        ) as analysis_span:
            logger.info(
                "Starting resource intelligence analysis",
                resource_type=primary_resource.get("type"),
                resource_name=primary_resource.get("name"),
                environment=environment,
            )
            
            inferred = await self._infer_required_resources(primary_resource, environment, preferences)
            recommendations = await self._generate_recommendations(primary_resource, environment)
            warnings = self._validate_resource_configuration(primary_resource, environment)
            adjustments = self._suggest_configuration_adjustments(primary_resource, environment, preferences)

            analysis_span.set_attributes({
                "inferred_resources_count": len(inferred),
                "recommendations_count": len(recommendations),
                "warnings_count": len(warnings),
            })

            result = ResourceIntelligenceResult(
                inferred_resources=inferred,
                recommendations=recommendations,
                warnings=warnings,
                configuration_adjustments=adjustments,
            )

            logger.info(
                "Resource intelligence analysis completed",
                inferred_count=len(inferred),
                recommendations_count=len(recommendations),
                warnings_count=len(warnings),
            )

            tracer.track_agent_metrics(
                "resource_analysis", 
                0.0, 
                True, 
                len(inferred)
            )

            return result

    async def _infer_required_resources(
        self, primary_resource: dict[str, Any], environment: str, preferences: dict[str, Any]
    ) -> list[dict[str, Any]]:
        inferred: list[dict[str, Any]] = []
        resource_type = primary_resource.get("type", "").lower()
        resource_name = primary_resource.get("name", "unnamed")

        if resource_type in ["webapp", "microsoft.web/sites"]:
            if not preferences.get("skip_app_service_plan", False):
                plan_name = primary_resource.get("app_service_plan") or f"{resource_name}-plan"
                plan_sku = self._determine_app_service_sku(environment, preferences)
                
                inferred.append({
                    "type": "app_service_plan",
                    "name": plan_name,
                    "sku": plan_sku,
                    "location": primary_resource.get("location", "westeurope"),
                    "os_type": primary_resource.get("os_type", "Linux"),
                    "reason": "Required for Web App hosting",
                })

        elif resource_type in ["aks_cluster", "microsoft.containerservice/managedclusters"]:
            if not preferences.get("existing_vnet"):
                vnet_name = f"{resource_name}-vnet"
                subnet_name = f"{resource_name}-subnet"
                
                inferred.extend([
                    {
                        "type": "virtual_network",
                        "name": vnet_name,
                        "address_space": ["10.0.0.0/16"],
                        "location": primary_resource.get("location", "westeurope"),
                        "reason": "Network isolation for AKS cluster",
                    },
                    {
                        "type": "subnet",
                        "name": subnet_name,
                        "vnet_name": vnet_name,
                        "address_prefix": "10.0.1.0/24",
                        "reason": "Dedicated subnet for AKS nodes",
                    },
                ])

            if environment in ["staging", "prod"] and not preferences.get("skip_monitoring"):
                workspace_name = f"{resource_name}-logs"
                inferred.append({
                    "type": "log_analytics_workspace",
                    "name": workspace_name,
                    "sku": "PerGB2018",
                    "retention_days": 90 if environment == "prod" else 30,
                    "location": primary_resource.get("location", "westeurope"),
                    "reason": "Required for AKS monitoring and logging",
                })

        elif resource_type in ["sql_database", "microsoft.sql/servers/databases"]:
            server_name = primary_resource.get("server_name")
            if not server_name:
                server_name = f"{resource_name}-server"
                inferred.append({
                    "type": "sql_server",
                    "name": server_name,
                    "admin_username": "sqladmin",
                    "location": primary_resource.get("location", "westeurope"),
                    "version": "12.0",
                    "reason": "Required SQL Server instance for database",
                })

        return inferred

    async def _generate_recommendations(
        self, primary_resource: dict[str, Any], environment: str
    ) -> list[ResourceRecommendation]:
        recommendations: list[ResourceRecommendation] = []
        resource_type = primary_resource.get("type", "").lower()
        resource_name = primary_resource.get("name", "unnamed")

        complementary = self._complementary_resources.get(resource_type, [])
        
        for comp_resource in complementary:
            should_recommend = True
            
            if comp_resource["type"] == "application_insights" and environment == "dev":
                should_recommend = comp_resource["priority"] == "high"
            elif comp_resource["type"] == "key_vault" and environment == "dev":
                should_recommend = False
            
            if should_recommend:
                rec = ResourceRecommendation(
                    resource_type=comp_resource["type"],
                    resource_name=f"{resource_name}-{comp_resource['type'].replace('_', '-')}",
                    reason=comp_resource["reason"],
                    priority=comp_resource["priority"],
                    configuration=comp_resource.get("configuration", {}),
                    estimated_cost_impact=self._estimate_cost_impact(comp_resource["type"], environment),
                )
                recommendations.append(rec)

        if resource_type in ["webapp"] and environment in ["staging", "prod"]:
            recommendations.append(
                ResourceRecommendation(
                    resource_type="autoscale_setting",
                    resource_name=f"{resource_name}-autoscale",
                    reason="Automatic scaling based on demand",
                    priority="medium",
                    configuration={
                        "min_instances": 2 if environment == "prod" else 1,
                        "max_instances": 10 if environment == "prod" else 3,
                    },
                    estimated_cost_impact="variable",
                )
            )

        return recommendations

    def _validate_resource_configuration(self, resource: dict[str, Any], environment: str) -> list[str]:
        warnings: list[str] = []
        resource_type = resource.get("type", "").lower()
        
        if resource_type in ["webapp"] and environment == "prod":
            if not resource.get("https_only", True):
                warnings.append("Production Web Apps should enforce HTTPS only")
            
            if not resource.get("backup_enabled"):
                warnings.append("Production Web Apps should have backup enabled")

        elif resource_type in ["aks_cluster"]:
            if environment == "prod" and resource.get("node_count", 1) < 3:
                warnings.append("Production AKS clusters should have at least 3 nodes for high availability")
            
            if not resource.get("network_policy"):
                warnings.append("AKS clusters should use network policies for security")

        elif resource_type in ["sql_server"]:
            if not resource.get("firewall_rules"):
                warnings.append("SQL Server should have firewall rules configured")
            
            if environment == "prod" and not resource.get("geo_backup_enabled"):
                warnings.append("Production SQL Servers should have geo-redundant backup enabled")

        return warnings

    def _suggest_configuration_adjustments(
        self, resource: dict[str, Any], environment: str, preferences: dict[str, Any]
    ) -> dict[str, Any]:
        adjustments: dict[str, Any] = {}
        resource_type = resource.get("type", "").lower()
        
        if resource_type in ["webapp"]:
            if environment == "dev" and not preferences.get("preserve_sku"):
                adjustments["sku"] = "F1"
            elif environment == "prod":
                adjustments["sku"] = "P1v2"
                adjustments["https_only"] = True
                adjustments["min_tls_version"] = "1.2"

        elif resource_type in ["aks_cluster"]:
            if environment == "dev":
                adjustments["node_count"] = 1
                adjustments["vm_size"] = "Standard_B2s"
            elif environment == "prod":
                adjustments["node_count"] = 3
                adjustments["vm_size"] = "Standard_D2s_v3"
                adjustments["enable_rbac"] = True

        return adjustments

    def _determine_app_service_sku(self, environment: str, preferences: dict[str, Any]) -> str:
        if preferences.get("sku"):
            return preferences["sku"]
        
        sku_map = {
            "dev": "F1",
            "staging": "S1", 
            "prod": "P1v2",
        }
        return sku_map.get(environment, "B1")

    def _estimate_cost_impact(self, resource_type: str, environment: str) -> str:
        cost_matrix = {
            ("application_insights", "dev"): "low",
            ("application_insights", "prod"): "medium",
            ("key_vault", "dev"): "low",
            ("key_vault", "prod"): "low",
            ("container_registry", "dev"): "low",
            ("container_registry", "prod"): "medium",
            ("log_analytics_workspace", "dev"): "low",
            ("log_analytics_workspace", "prod"): "medium",
            ("storage_account", "dev"): "low",
            ("storage_account", "prod"): "medium",
        }
        
        return cost_matrix.get((resource_type, environment), "unknown")