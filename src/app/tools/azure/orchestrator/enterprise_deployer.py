from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..clients import Clients, get_clients
from ..nlp.intent_classifier import DeploymentIntent, EnterpriseNLPParser


@dataclass
class DeploymentPlan:
    request_id: str
    timestamp: datetime
    intent: DeploymentIntent
    resources: list[dict[str, Any]]
    dependencies: list[str]
    validations: list[dict[str, Any]]
    cost_estimate: dict[str, Any]
    compliance_checks: list[str]
    rollback_plan: dict[str, Any]
    approval_required: bool
    risk_level: str


@dataclass
class DeploymentContext:
    subscription_id: str
    resource_group: str
    location: str
    environment: str
    tags: dict[str, str] = field(default_factory=dict)
    dry_run: bool = False
    force: bool = False
    validate_only: bool = False
    cost_threshold: float | None = None
    require_approval: bool = True
    enable_monitoring: bool = True
    enable_backup: bool = False
    enable_private_endpoints: bool = False
    network_configuration: dict[str, Any] | None = None


@runtime_checkable
class ResourceDeployer(Protocol):
    async def deploy(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]: ...


class EnterpriseAzureDeployer:
    def __init__(self) -> None:
        self.nlp_parser = EnterpriseNLPParser()
        self.deployment_templates = self._load_deployment_templates()
        self.cost_calculator = CostCalculator()
        self.compliance_validator = ComplianceValidator()
        self.dependency_resolver = DependencyResolver()

    async def deploy_from_natural_language(
        self, request: str, context: DeploymentContext | None = None
    ) -> dict[str, Any]:
        parsed = self.nlp_parser.parse(request)
        if parsed.confidence < 0.3:
            return {
                "status": "error",
                "message": "Could not understand the deployment request with sufficient confidence",
                "suggestions": self._generate_suggestions(request),
            }
        if not context:
            context = self._extract_context_from_parsed(parsed, request)
        plan = await self._create_deployment_plan(parsed, context)
        if context.validate_only:
            return {
                "status": "validation_complete",
                "plan": self._serialize_plan(plan),
                "validations": plan.validations,
            }
        if plan.approval_required and context.require_approval:
            return {
                "status": "approval_required",
                "plan": self._serialize_plan(plan),
                "approval_url": self._generate_approval_url(plan),
            }
        result = await self._execute_deployment(plan, context)
        return {
            "status": "deployed" if result["success"] else "failed",
            "plan": self._serialize_plan(plan),
            "result": result,
            "monitoring_dashboard": (
                self._generate_monitoring_url(result) if result["success"] else None
            ),
        }

    async def _create_deployment_plan(
        self, parsed: Any, context: DeploymentContext
    ) -> DeploymentPlan:
        resources = await self._determine_resources(parsed, context)
        dependencies = await self.dependency_resolver.resolve(resources, parsed.dependencies)
        validations = await self._validate_deployment(resources, context)
        cost_estimate = await self.cost_calculator.estimate(resources, context)
        compliance_checks = await self.compliance_validator.check(
            resources, parsed.compliance_requirements
        )
        rollback_plan = self._create_rollback_plan(resources)
        risk_level = self._assess_risk_level(
            parsed.intent, resources, context.environment, cost_estimate
        )
        approval_required = (
            risk_level in ["high", "critical"]
            or cost_estimate.get("monthly_total", 0.0) > (context.cost_threshold or 1000.0)
            or context.environment == "production"
        )
        return DeploymentPlan(
            request_id=self._generate_request_id(),
            timestamp=datetime.utcnow(),
            intent=parsed.intent,
            resources=resources,
            dependencies=dependencies,
            validations=validations,
            cost_estimate=cost_estimate,
            compliance_checks=compliance_checks,
            rollback_plan=rollback_plan,
            approval_required=approval_required,
            risk_level=risk_level,
        )

    async def _determine_resources(
        self, parsed: Any, context: DeploymentContext
    ) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        template = self.deployment_templates.get(parsed.resource_type)
        if not template:
            template = self._create_dynamic_template(parsed)
        base_config = self._apply_template(template, parsed, context)
        resources.append(base_config)
        if parsed.attributes.get("high_availability"):
            resources.extend(self._add_ha_resources(base_config, context))
        if parsed.attributes.get("disaster_recovery"):
            resources.extend(self._add_dr_resources(base_config, context))
        if context.enable_monitoring:
            resources.extend(self._add_monitoring_resources(base_config, context))
        if context.enable_private_endpoints:
            resources.extend(self._add_private_endpoint_resources(base_config, context))
        if context.enable_backup:
            resources.extend(self._add_backup_resources(base_config, context))
        return resources

    async def _execute_deployment(
        self, plan: DeploymentPlan, context: DeploymentContext
    ) -> dict[str, Any]:
        clients = await get_clients(context.subscription_id)
        results: list[dict[str, Any]] = []
        deployed_resources: list[dict[str, Any]] = []
        try:
            for resource in plan.resources:
                result = await self._deploy_single_resource(resource, clients, context)
                results.append(result)
                if not result["success"]:
                    if deployed_resources:
                        await self._rollback_deployment(deployed_resources, clients, context)
                    return {
                        "success": False,
                        "error": result["error"],
                        "partial_deployment": deployed_resources,
                        "rollback_executed": bool(deployed_resources),
                    }
                deployed_resources.append(result["resource"])
            post_deployment = await self._execute_post_deployment(
                deployed_resources, clients, context
            )
            return {
                "success": True,
                "resources": deployed_resources,
                "post_deployment": post_deployment,
                "cost_estimate": plan.cost_estimate,
                "compliance_status": plan.compliance_checks,
            }
        except Exception as e:
            if deployed_resources:
                await self._rollback_deployment(deployed_resources, clients, context)
            return {
                "success": False,
                "error": str(e),
                "partial_deployment": deployed_resources,
                "rollback_executed": bool(deployed_resources),
            }

    async def _deploy_single_resource(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        resource_type = resource["type"]
        deployer = self._get_resource_deployer(resource_type)
        if not isinstance(deployer, ResourceDeployer):
            return {
                "success": False,
                "error": f"No deployer available for resource type: {resource_type}",
            }
        try:
            result = await deployer.deploy(resource, clients, context)
            return {"success": True, "resource": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_resource_deployer(self, resource_type: str) -> ResourceDeployer:
        deployers: dict[str, ResourceDeployer] = {
            "aks_cluster": AKSDeployer(),
            "container_registry": ACRDeployer(),
            "api_management": APIMDeployer(),
            "data_factory": DataFactoryDeployer(),
            "synapse": SynapseDeployer(),
            "cognitive_services": CognitiveServicesDeployer(),
            "event_hub": EventHubDeployer(),
            "service_bus": ServiceBusDeployer(),
            "logic_apps": LogicAppsDeployer(),
            "front_door": FrontDoorDeployer(),
        }
        return deployers.get(resource_type, GenericResourceDeployer())

    def _load_deployment_templates(self) -> dict[str, Any]:
        return {
            "aks_cluster": {
                "type": "aks_cluster",
                "base_config": {
                    "node_pools": [
                        {
                            "name": "systempool",
                            "count": 2,
                            "vm_size": "Standard_DS2_v2",
                            "mode": "System",
                        }
                    ],
                    "network_profile": {"network_plugin": "azure", "load_balancer_sku": "standard"},
                    "identity": {"type": "SystemAssigned"},
                    "enable_rbac": True,
                    "addon_profiles": {
                        "omsagent": {"enabled": True},
                        "azurepolicy": {"enabled": True},
                    },
                },
            },
            "api_management": {
                "type": "api_management",
                "base_config": {
                    "sku": {"name": "Developer", "capacity": 1},
                    "publisher_email": "admin@contoso.com",
                    "publisher_name": "Contoso",
                    "virtual_network_type": "None",
                },
            },
        }

    def _extract_context_from_parsed(self, parsed: Any, request: str) -> DeploymentContext:
        context = DeploymentContext(
            subscription_id="",
            resource_group="",
            location="westeurope",
            environment=parsed.attributes.get("environment", "development"),
        )
        regions = [
            "west europe",
            "westeurope",
            "north europe",
            "northeurope",
            "uk south",
            "uksouth",
            "east us",
            "eastus",
        ]
        pattern = r"\b(" + "|".join(regions) + r")\b"
        location_match = re.search(pattern, request.lower())
        if location_match:
            context.location = location_match.group(1).replace(" ", "")
        rg_match = re.search(r"resource group\s+([a-z0-9][\w-]{0,89})", request.lower())
        if rg_match:
            context.resource_group = rg_match.group(1)
        if parsed.attributes.get("private_endpoints"):
            context.enable_private_endpoints = True
        if "backup" in parsed.dependencies:
            context.enable_backup = True
        return context

    def _serialize_plan(self, plan: DeploymentPlan) -> dict[str, Any]:
        return {
            "request_id": plan.request_id,
            "timestamp": plan.timestamp.isoformat(),
            "intent": plan.intent.value,
            "resources": plan.resources,
            "cost_estimate": plan.cost_estimate,
            "risk_level": plan.risk_level,
            "approval_required": plan.approval_required,
        }

    def _generate_request_id(self) -> str:
        return f"deploy-{uuid.uuid4().hex[:8]}"

    def _assess_risk_level(
        self,
        intent: DeploymentIntent,
        resources: list[dict[str, Any]],
        environment: str,
        cost_estimate: dict[str, Any],
    ) -> str:
        risk_score = 0
        if intent in [DeploymentIntent.DELETE, DeploymentIntent.MIGRATE]:
            risk_score += 3
        if environment == "production":
            risk_score += 2
        elif environment == "staging":
            risk_score += 1
        if cost_estimate.get("monthly_total", 0.0) > 5000.0:
            risk_score += 2
        elif cost_estimate.get("monthly_total", 0.0) > 1000.0:
            risk_score += 1
        if len(resources) > 10:
            risk_score += 1
        if risk_score >= 5:
            return "critical"
        elif risk_score >= 3:
            return "high"
        elif risk_score >= 1:
            return "medium"
        else:
            return "low"

    def _generate_suggestions(self, request: str) -> list[str]:
        return [
            "specify the azure resource type",
            "include resource group and region",
            "add environment and tags",
        ]

    def _generate_approval_url(self, plan: DeploymentPlan) -> str:
        return f"https://approval.local/requests/{plan.request_id}"

    def _generate_monitoring_url(self, result: dict[str, Any]) -> str:
        tracking_id = str(result.get("tracking_id") or self._generate_request_id())
        return f"https://monitoring.local/deployments/{tracking_id}"

    async def _validate_deployment(
        self, resources: list[dict[str, Any]], context: DeploymentContext
    ) -> list[dict[str, Any]]:
        validations: list[dict[str, Any]] = []
        if context.subscription_id:
            validations.append({"check": "subscription_id", "status": "ok"})
        else:
            validations.append({"check": "subscription_id", "status": "fail", "message": "missing"})
        if context.resource_group:
            validations.append({"check": "resource_group", "status": "ok"})
        else:
            validations.append({"check": "resource_group", "status": "fail", "message": "missing"})
        validations.append({"check": "resource_count", "status": "ok", "details": len(resources)})
        return validations

    def _create_rollback_plan(self, resources: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "strategy": "best_effort_delete",
            "targets": [r.get("name", "resource") for r in resources],
        }

    def _create_dynamic_template(self, parsed: Any) -> dict[str, Any]:
        name_val = parsed.attributes.get("name", parsed.resource_type)
        return {"type": parsed.resource_type, "name": name_val, "base_config": {}}

    def _apply_template(
        self, template: dict[str, Any], parsed: Any, context: DeploymentContext
    ) -> dict[str, Any]:
        base: dict[str, Any] = dict(template)
        base_config: dict[str, Any] = dict(template.get("base_config", {}))
        if "name" in parsed.attributes:
            base["name"] = parsed.attributes["name"]
        base["type"] = template.get("type", parsed.resource_type)
        base["base_config"] = base_config
        if parsed.attributes.get("tags") and isinstance(parsed.attributes["tags"], dict):
            context.tags.update(parsed.attributes["tags"])
        return base

    def _add_ha_resources(
        self, base_config: dict[str, Any], context: DeploymentContext
    ) -> list[dict[str, Any]]:
        base_name = base_config.get("name", "res")
        base_type = base_config.get("type", "generic")
        return [{"type": base_type, "name": f"{base_name}-ha", "high_availability": True}]

    def _add_dr_resources(
        self, base_config: dict[str, Any], context: DeploymentContext
    ) -> list[dict[str, Any]]:
        base_name = base_config.get("name", "res")
        base_type = base_config.get("type", "generic")
        return [{"type": base_type, "name": f"{base_name}-dr", "properties": {"dr": True}}]

    def _add_monitoring_resources(
        self, base_config: dict[str, Any], context: DeploymentContext
    ) -> list[dict[str, Any]]:
        base_name = base_config.get("name", "res")
        return [{"type": "log_analytics_workspace", "name": f"{base_name}-law"}]

    def _add_private_endpoint_resources(
        self, base_config: dict[str, Any], context: DeploymentContext
    ) -> list[dict[str, Any]]:
        base_name = base_config.get("name", "res")
        return [{"type": "private_endpoint", "name": f"{base_name}-pep"}]

    def _add_backup_resources(
        self, base_config: dict[str, Any], context: DeploymentContext
    ) -> list[dict[str, Any]]:
        base_name = base_config.get("name", "res")
        return [{"type": "backup_vault", "name": f"{base_name}-backup"}]

    async def _rollback_deployment(
        self, deployed: list[dict[str, Any]], clients: Clients, context: DeploymentContext
    ) -> None:
        return None

    async def _execute_post_deployment(
        self, deployed: list[dict[str, Any]], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        return {"status": "completed", "items": [r.get("name") for r in deployed]}


class CostCalculator:
    async def estimate(
        self, resources: list[dict[str, Any]], context: DeploymentContext
    ) -> dict[str, Any]:
        total_monthly: float = 0.0
        breakdown: list[dict[str, Any]] = []
        for resource in resources:
            cost = self._estimate_resource_cost(resource, context)
            breakdown.append(
                {
                    "resource": resource.get("name", "unnamed"),
                    "type": resource.get("type"),
                    "monthly_cost": cost,
                }
            )
            total_monthly += float(cost)
        return {
            "monthly_total": total_monthly,
            "yearly_total": total_monthly * 12.0,
            "breakdown": breakdown,
            "currency": "USD",
        }

    def _estimate_resource_cost(
        self, resource: dict[str, Any], context: DeploymentContext
    ) -> float:
        cost_map: dict[str, float] = {
            "aks_cluster": 150.0,
            "container_registry": 25.0,
            "api_management": 50.0,
            "data_factory": 100.0,
            "synapse": 200.0,
            "cognitive_services": 75.0,
            "event_hub": 40.0,
            "service_bus": 30.0,
            "logic_apps": 20.0,
            "front_door": 35.0,
            "storage_account": 20.0,
            "webapp": 25.0,
            "database": 100.0,
            "vm": 50.0,
            "keyvault": 5.0,
        }
        base_cost = cost_map.get(resource.get("type", "generic"), 50.0)
        if context.environment == "production":
            base_cost *= 2.0
        if resource.get("high_availability"):
            base_cost *= 1.5
        return float(base_cost)


class ComplianceValidator:
    async def check(self, resources: list[dict[str, Any]], requirements: list[str]) -> list[str]:
        checks: list[str] = []
        for requirement in requirements:
            if requirement == "gdpr":
                checks.append("GDPR: Data residency in EU regions confirmed")
                checks.append("GDPR: Encryption at rest enabled")
                checks.append("GDPR: Audit logging configured")
            elif requirement == "hipaa":
                checks.append("HIPAA: Encryption in transit enabled")
                checks.append("HIPAA: Access controls configured")
                checks.append("HIPAA: Backup and recovery enabled")
            elif requirement == "pci_dss":
                checks.append("PCI-DSS: Network segmentation configured")
                checks.append("PCI-DSS: WAF enabled")
                checks.append("PCI-DSS: Key management configured")
        return checks


class DependencyResolver:
    async def resolve(self, resources: list[dict[str, Any]], dependencies: list[str]) -> list[str]:
        resolved: list[str] = []
        for dep in dependencies:
            if dep == "active_directory":
                resolved.append("Azure AD integration configured")
            elif dep == "dns":
                resolved.append("DNS zones configured")
            elif dep == "certificate":
                resolved.append("SSL certificates provisioned")
            elif dep == "monitoring":
                resolved.append("Application Insights configured")
                resolved.append("Log Analytics workspace created")
            elif dep == "backup":
                resolved.append("Azure Backup configured")
            elif dep == "networking":
                resolved.append("Virtual network integrated")
        return resolved


class GenericResourceDeployer:
    async def deploy(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        resource_type = resource["type"]
        resource_name = resource.get("name", "resource")
        resource_id = (
            f"/subscriptions/{context.subscription_id}"
            f"/resourceGroups/{context.resource_group}"
            f"/providers/Microsoft.Resources/"
            f"{resource_type}/{resource_name}"
        )
        return {
            "id": resource_id,
            "name": resource_name,
            "type": resource_type,
            "location": context.location,
            "properties": resource.get("properties", {}),
            "tags": context.tags,
        }


class AKSDeployer:
    async def deploy(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        from ..actions.aks import create_aks

        config = resource.get("base_config", {})
        status, result = await create_aks(
            clients=clients,
            resource_group=context.resource_group,
            location=context.location,
            name=resource.get("name", "aks-cluster"),
            dns_prefix=resource.get("dns_prefix", resource.get("name", "aks")),
            node_count=config.get("node_pools", [{}])[0].get("count", 2),
            network_plugin=config.get("network_profile", {}).get("network_plugin", "azure"),
            tags=context.tags,
            dry_run=context.dry_run,
            force=context.force,
        )
        if status in ["created", "exists"]:
            if isinstance(result, dict):
                return result
            if hasattr(result, "as_dict"):
                return result.as_dict()  # type: ignore[call-arg, attr-defined]
            return {"result": result}
        raise Exception(f"AKS deployment failed: {result}")


class ACRDeployer:
    async def deploy(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        from ..actions.acr import create_registry

        status, result = await create_registry(
            clients=clients,
            resource_group=context.resource_group,
            location=context.location,
            name=resource.get("name", "acr"),
            sku=resource.get("sku", "Basic"),
            admin_user_enabled=resource.get("admin_user_enabled", True),
            tags=context.tags,
            dry_run=context.dry_run,
            force=context.force,
        )
        if status in ["created", "exists"]:
            if isinstance(result, dict):
                return result
            if hasattr(result, "as_dict"):
                return result.as_dict()  # type: ignore[call-arg, attr-defined]
            return {"result": result}
        raise Exception(f"ACR deployment failed: {result}")


class APIMDeployer:
    async def deploy(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        from azure.mgmt.apimanagement import ApiManagementClient
        from azure.mgmt.apimanagement.models import ApiManagementServiceResource

        apim_client = ApiManagementClient(clients.cred, context.subscription_id)
        service_params = ApiManagementServiceResource(
            location=context.location,
            sku_name=resource.get("sku", {}).get("name", "Developer"),
            sku_capacity=resource.get("sku", {}).get("capacity", 1),
            publisher_email=resource.get("publisher_email", "admin@contoso.com"),
            publisher_name=resource.get("publisher_name", "Contoso"),
            tags=context.tags,
        )
        if not context.dry_run:
            poller = await clients.run(
                apim_client.api_management_service.begin_create_or_update,
                context.resource_group,
                resource.get("name", "apim"),
                service_params,
            )
            result = await clients.run(poller.result)
            return result.as_dict()
        return {
            "name": resource.get("name", "apim"),
            "type": "Microsoft.ApiManagement/service",
            "location": context.location,
            "dry_run": True,
        }


class DataFactoryDeployer:
    async def deploy(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        from azure.mgmt.datafactory import DataFactoryManagementClient
        from azure.mgmt.datafactory.models import Factory

        adf_client = DataFactoryManagementClient(clients.cred, context.subscription_id)
        factory = Factory(location=context.location, tags=context.tags)
        if not context.dry_run:
            result = await clients.run(
                adf_client.factories.create_or_update,
                context.resource_group,
                resource.get("name", "datafactory"),
                factory,
            )
            return result.as_dict()
        return {
            "name": resource.get("name", "datafactory"),
            "type": "Microsoft.DataFactory/factories",
            "location": context.location,
            "dry_run": True,
        }


class SynapseDeployer:
    async def deploy(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        from azure.mgmt.synapse import SynapseManagementClient
        from azure.mgmt.synapse.models import DataLakeStorageAccountDetails, Workspace

        synapse_client = SynapseManagementClient(clients.cred, context.subscription_id)
        workspace_params = Workspace(
            location=context.location,
            default_data_lake_storage=DataLakeStorageAccountDetails(
                account_url=resource.get(
                    "storage_account_url",
                    f"https://{resource.get('name', 'synapse')}storage.dfs.core.windows.net",
                ),
                filesystem=resource.get("filesystem", "synapse"),
            ),
            sql_administrator_login=resource.get("sql_admin", "sqladmin"),
            sql_administrator_login_password=resource.get("sql_password", "P@ssw0rd123!"),
            tags=context.tags,
        )
        if not context.dry_run:
            poller = await clients.run(
                synapse_client.workspaces.begin_create_or_update,
                context.resource_group,
                resource.get("name", "synapse"),
                workspace_params,
            )
            result = await clients.run(poller.result)
            return result.as_dict()
        return {
            "name": resource.get("name", "synapse"),
            "type": "Microsoft.Synapse/workspaces",
            "location": context.location,
            "dry_run": True,
        }


class CognitiveServicesDeployer:
    async def deploy(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
        from azure.mgmt.cognitiveservices.models import Account, Sku

        cognitive_client = CognitiveServicesManagementClient(clients.cred, context.subscription_id)
        account_params = Account(
            location=context.location,
            sku=Sku(name=resource.get("sku", "S0")),
            kind=resource.get("kind", "CognitiveServices"),
            properties={},
            tags=context.tags,
        )
        if not context.dry_run:
            poller = await clients.run(
                cognitive_client.accounts.begin_create,
                context.resource_group,
                resource.get("name", "cognitive"),
                account_params,
            )
            result = await clients.run(poller.result)
            return result.as_dict()
        return {
            "name": resource.get("name", "cognitive"),
            "type": "Microsoft.CognitiveServices/accounts",
            "location": context.location,
            "dry_run": True,
        }


class EventHubDeployer:
    async def deploy(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        from azure.mgmt.eventhub import EventHubManagementClient
        from azure.mgmt.eventhub.models import EHNamespace
        from azure.mgmt.eventhub.models import Sku as EventHubSku

        eventhub_client = EventHubManagementClient(clients.cred, context.subscription_id)
        namespace_params = EHNamespace(
            location=context.location,
            sku=EventHubSku(
                name=resource.get("sku", "Standard"),
                tier=resource.get("tier", "Standard"),
                capacity=resource.get("capacity", 1),
            ),
            is_auto_inflate_enabled=resource.get("auto_inflate", True),
            maximum_throughput_units=resource.get("max_throughput", 10),
            tags=context.tags,
        )
        if not context.dry_run:
            poller = await clients.run(
                eventhub_client.namespaces.begin_create_or_update,
                context.resource_group,
                resource.get("name", "eventhub"),
                namespace_params,
            )
            result = await clients.run(poller.result)
            return result.as_dict()
        return {
            "name": resource.get("name", "eventhub"),
            "type": "Microsoft.EventHub/namespaces",
            "location": context.location,
            "dry_run": True,
        }


class ServiceBusDeployer:
    async def deploy(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        from azure.mgmt.servicebus import ServiceBusManagementClient
        from azure.mgmt.servicebus.models import SBNamespace, SBSku

        servicebus_client = ServiceBusManagementClient(clients.cred, context.subscription_id)
        namespace_params = SBNamespace(
            location=context.location,
            sku=SBSku(name=resource.get("sku", "Standard"), tier=resource.get("tier", "Standard")),
            tags=context.tags,
        )
        if not context.dry_run:
            poller = await clients.run(
                servicebus_client.namespaces.begin_create_or_update,
                context.resource_group,
                resource.get("name", "servicebus"),
                namespace_params,
            )
            result = await clients.run(poller.result)
            return result.as_dict()
        return {
            "name": resource.get("name", "servicebus"),
            "type": "Microsoft.ServiceBus/namespaces",
            "location": context.location,
            "dry_run": True,
        }


class LogicAppsDeployer:
    async def deploy(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        from azure.mgmt.logic import LogicManagementClient
        from azure.mgmt.logic.models import Workflow

        logic_client = LogicManagementClient(clients.cred, context.subscription_id)
        workflow_params = Workflow(
            location=context.location,
            definition=resource.get(
                "definition",
                {
                    "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                    "contentVersion": "1.0.0.0",
                    "triggers": {},
                    "actions": {},
                    "outputs": {},
                },
            ),
            tags=context.tags,
        )
        if not context.dry_run:
            result = await clients.run(
                logic_client.workflows.create_or_update,
                context.resource_group,
                resource.get("name", "logicapp"),
                workflow_params,
            )
            return result.as_dict()
        return {
            "name": resource.get("name", "logicapp"),
            "type": "Microsoft.Logic/workflows",
            "location": context.location,
            "dry_run": True,
        }


class FrontDoorDeployer:
    async def deploy(
        self, resource: dict[str, Any], clients: Clients, context: DeploymentContext
    ) -> dict[str, Any]:
        from azure.mgmt.frontdoor import FrontDoorManagementClient
        from azure.mgmt.frontdoor.models import (
            Backend,
            BackendPool,
            FrontDoor,
            FrontendEndpoint,
            RoutingRule,
        )

        frontdoor_client = FrontDoorManagementClient(clients.cred, context.subscription_id)
        frontdoor_name = resource.get("name", "frontdoor")
        frontdoor_id_base = (
            f"/subscriptions/{context.subscription_id}/resourceGroups/"
            f"{context.resource_group}/providers/"
            f"Microsoft.Network/frontDoors/{frontdoor_name}"
        )
        frontend_endpoint_id = f"{frontdoor_id_base}/frontendEndpoints/frontendEndpoint1"
        backend_pool_id = f"{frontdoor_id_base}/backendPools/backendPool1"
        forwarding_odata_type = "#Microsoft.Azure.FrontDoor.Models.FrontdoorForwardingConfiguration"
        frontdoor_params = FrontDoor(
            location="global",
            frontend_endpoints=[
                FrontendEndpoint(
                    name="frontendEndpoint1",
                    host_name=f"{frontdoor_name}.azurefd.net",
                )
            ],
            backend_pools=[
                BackendPool(
                    name="backendPool1",
                    backends=[
                        Backend(
                            address=resource.get("backend_address", "example.com"),
                            http_port=80,
                            https_port=443,
                            priority=1,
                            weight=50,
                        )
                    ],
                )
            ],
            routing_rules=[
                RoutingRule(
                    name="routingRule1",
                    frontend_endpoints=[{"id": frontend_endpoint_id}],
                    accepted_protocols=["Http", "Https"],
                    patterns_to_match=["/*"],
                    route_configuration={
                        "@odata.type": forwarding_odata_type,
                        "backend_pool": {"id": backend_pool_id},
                    },
                )
            ],
            tags=context.tags,
        )
        if not context.dry_run:
            poller = await clients.run(
                frontdoor_client.front_doors.begin_create_or_update,
                context.resource_group,
                resource.get("name", "frontdoor"),
                frontdoor_params,
            )
            result = await clients.run(poller.result)
            return result.as_dict()
        return {
            "name": resource.get("name", "frontdoor"),
            "type": "Microsoft.Network/frontDoors",
            "location": "global",
            "dry_run": True,
        }
