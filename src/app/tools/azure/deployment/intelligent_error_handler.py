from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace

from app.core.logging import get_logger

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class ErrorAnalysis:
    error_type: str
    error_category: str
    root_cause: str
    severity: str
    suggested_actions: list[str] = field(default_factory=list)
    alternative_configurations: list[dict[str, Any]] = field(default_factory=list)
    recommended_regions: list[str] = field(default_factory=list)
    estimated_resolution_time_minutes: int = 5
    retry_feasible: bool = True
    requires_manual_intervention: bool = False


@dataclass
class RemediationPlan:
    primary_action: str
    backup_actions: list[str]
    configuration_adjustments: dict[str, Any]
    resource_alternatives: list[dict[str, Any]]
    estimated_success_probability: float
    execution_order: list[str]


class IntelligentErrorHandler:
    def __init__(self) -> None:
        self._error_patterns = self._initialize_error_patterns()
        self._region_alternatives = self._initialize_region_alternatives()
        self._sku_alternatives = self._initialize_sku_alternatives()
        self._network_cidr_pool = self._initialize_cidr_pool()

    def _initialize_error_patterns(self) -> dict[str, dict[str, Any]]:
        return {
            "QuotaExceededError": {
                "category": "capacity",
                "severity": "high",
                "patterns": [
                    r"quota.*exceeded",
                    r"resource limit.*reached",
                    r"insufficient.*capacity",
                    r"not enough.*cores",
                ],
                "remediation_type": "capacity_management",
            },
            "AuthorizationError": {
                "category": "security",
                "severity": "high",
                "patterns": [
                    r"authorization.*failed",
                    r"access.*denied",
                    r"insufficient.*permissions",
                    r"rbac.*denied",
                ],
                "remediation_type": "permission_escalation",
            },
            "InvalidSkuError": {
                "category": "configuration",
                "severity": "medium",
                "patterns": [
                    r"sku.*not.*available",
                    r"invalid.*sku",
                    r"sku.*not.*supported",
                    r"tier.*unavailable",
                ],
                "remediation_type": "sku_adjustment",
            },
            "NetworkConflictError": {
                "category": "network",
                "severity": "medium",
                "patterns": [
                    r"address.*space.*conflict",
                    r"cidr.*overlap",
                    r"subnet.*conflict",
                    r"network.*already.*exists",
                ],
                "remediation_type": "network_reconfiguration",
            },
            "ResourceNotFoundError": {
                "category": "dependency",
                "severity": "medium",
                "patterns": [
                    r"resource.*not.*found",
                    r"parent.*resource.*missing",
                    r"dependency.*not.*met",
                    r"resource.*does.*not.*exist",
                ],
                "remediation_type": "dependency_resolution",
            },
            "TimeoutError": {
                "category": "performance",
                "severity": "medium",
                "patterns": [
                    r"operation.*timed.*out",
                    r"request.*timeout",
                    r"deployment.*timeout",
                    r"provisioning.*timeout",
                ],
                "remediation_type": "retry_optimization",
            },
            "RegionCapacityError": {
                "category": "capacity",
                "severity": "high",
                "patterns": [
                    r"region.*capacity.*exceeded",
                    r"location.*unavailable",
                    r"datacenter.*capacity",
                    r"availability.*zone.*full",
                ],
                "remediation_type": "region_migration",
            },
        }

    def _initialize_region_alternatives(self) -> dict[str, list[str]]:
        return {
            "westeurope": ["northeurope", "westeurope2", "francecentral", "germanywestcentral"],
            "eastus": ["eastus2", "centralus", "southcentralus", "westus2"],
            "southeastasia": ["eastasia", "japaneast", "australiaeast", "koreacentral"],
            "uksouth": ["ukwest", "northeurope", "westeurope"],
            "australiaeast": ["australiasoutheast", "southeastasia", "eastasia"],
            "centralindia": ["southindia", "westindia", "southeastasia"],
            "canadacentral": ["canadaeast", "eastus2", "centralus"],
            "brazilsouth": ["southcentralus", "eastus2", "centralus"],
        }

    def _initialize_sku_alternatives(self) -> dict[str, dict[str, list[str]]]:
        return {
            "virtual_machines": {
                "Standard_D2s_v3": ["Standard_D2as_v4", "Standard_B2s", "Standard_D2_v3"],
                "Standard_D4s_v3": ["Standard_D4as_v4", "Standard_B4ms", "Standard_D4_v3"],
                "Standard_F2s_v2": ["Standard_F2s", "Standard_D2s_v3", "Standard_B2s"],
                "Standard_B1s": ["Standard_B1ms", "Standard_A1_v2", "Standard_D1_v2"],
            },
            "app_service": {
                "P1v2": ["P1v3", "S1", "P1"],
                "P2v2": ["P2v3", "S2", "P2"],
                "S1": ["B1", "P1v2", "S2"],
                "F1": ["D1", "B1"],
                "B1": ["S1", "F1"],
            },
            "storage_account": {
                "Premium_LRS": ["Standard_LRS", "Standard_ZRS", "Premium_ZRS"],
                "Standard_GRS": ["Standard_LRS", "Standard_RAGRS", "Standard_ZRS"],
                "Standard_LRS": ["Standard_ZRS", "Standard_GRS"],
            },
            "sql_database": {
                "S0": ["S1", "Basic", "GP_S_Gen5_1"],
                "S1": ["S2", "S0", "GP_S_Gen5_2"],
                "P1": ["P2", "S3", "GP_Gen5_2"],
                "GP_Gen5_2": ["GP_S_Gen5_2", "GP_Gen5_4", "S2"],
            },
        }

    def _initialize_cidr_pool(self) -> list[str]:
        return [
            "10.1.0.0/16",
            "10.2.0.0/16",
            "10.3.0.0/16",
            "172.16.0.0/16",
            "172.17.0.0/16",
            "172.18.0.0/16",
            "192.168.1.0/24",
            "192.168.2.0/24",
            "192.168.3.0/24",
        ]

    async def analyze_error(
        self,
        error: Exception,
        context: dict[str, Any],
        deployment_history: list[dict[str, Any]] | None = None,
    ) -> ErrorAnalysis:
        with tracer.start_as_current_span(
            "analyze_error",
            attributes={
                "error_type": type(error).__name__,
                "has_context": bool(context),
                "has_history": bool(deployment_history),
            },
        ) as span:
            error_message = str(error).lower()
            error_type_name = type(error).__name__

            logger.info(
                "Starting intelligent error analysis",
                error_type=error_type_name,
                error_message_length=len(error_message),
                context_keys=list(context.keys()),
                history_entries=len(deployment_history or []),
            )

            error_category = self._categorize_error(error_message)
            root_cause = await self._determine_root_cause(
                error_message, context, deployment_history
            )

            analysis = ErrorAnalysis(
                error_type=error_type_name,
                error_category=error_category["category"],
                root_cause=root_cause,
                severity=error_category["severity"],
            )

            if error_category["category"] == "capacity":
                analysis = await self._analyze_capacity_error(analysis, error_message, context)
            elif error_category["category"] == "configuration":
                analysis = await self._analyze_configuration_error(analysis, error_message, context)
            elif error_category["category"] == "network":
                analysis = await self._analyze_network_error(analysis, error_message, context)
            elif error_category["category"] == "security":
                analysis = await self._analyze_security_error(analysis, error_message, context)
            elif error_category["category"] == "dependency":
                analysis = await self._analyze_dependency_error(analysis, error_message, context)
            else:
                analysis = await self._analyze_generic_error(analysis, error_message, context)

            span.set_attributes(
                {
                    "analysis_category": analysis.error_category,
                    "analysis_severity": analysis.severity,
                    "suggested_actions_count": len(analysis.suggested_actions),
                    "alternatives_count": len(analysis.alternative_configurations),
                    "retry_feasible": analysis.retry_feasible,
                }
            )

            logger.info(
                "Error analysis completed",
                error_category=analysis.error_category,
                severity=analysis.severity,
                suggested_actions_count=len(analysis.suggested_actions),
                retry_feasible=analysis.retry_feasible,
                manual_intervention_required=analysis.requires_manual_intervention,
            )

            return analysis

    def _categorize_error(self, error_message: str) -> dict[str, Any]:
        for _error_type, config in self._error_patterns.items():
            for pattern in config["patterns"]:
                if re.search(pattern, error_message, re.IGNORECASE):
                    return config

        return {"category": "unknown", "severity": "medium", "remediation_type": "generic"}

    async def _determine_root_cause(
        self,
        error_message: str,
        context: dict[str, Any],
        history: list[dict[str, Any]] | None,
    ) -> str:
        resource_type = context.get("resource_type", "unknown")
        location = context.get("location", "unknown")

        if "quota" in error_message:
            return f"Resource quota exceeded for {resource_type} in {location}"
        elif "permission" in error_message:
            return f"Insufficient permissions for {resource_type} deployment"
        elif "sku" in error_message:
            return f"Requested SKU unavailable for {resource_type} in {location}"
        elif "network" in error_message or "cidr" in error_message:
            return f"Network configuration conflict in {location}"
        elif "not found" in error_message:
            return f"Dependent resource missing for {resource_type}"
        elif "timeout" in error_message:
            return f"Deployment timeout for {resource_type} in {location}"
        else:
            return f"Deployment failure for {resource_type}: {error_message[:100]}..."

    async def _analyze_capacity_error(
        self, analysis: ErrorAnalysis, error_message: str, context: dict[str, Any]
    ) -> ErrorAnalysis:
        current_location = context.get("location", "westeurope")
        resource_type = context.get("resource_type", "")

        analysis.recommended_regions = self._region_alternatives.get(current_location, [])

        if "cores" in error_message or "vm" in resource_type.lower():
            vm_sku = context.get("vm_size", context.get("sku", ""))
            if vm_sku and vm_sku in self._sku_alternatives.get("virtual_machines", {}):
                alternatives = self._sku_alternatives["virtual_machines"][vm_sku]
                analysis.alternative_configurations = [
                    {"vm_size": alt, "reason": f"Alternative to {vm_sku}"}
                    for alt in alternatives[:3]
                ]

        alternative_region = (
            analysis.recommended_regions[0] if analysis.recommended_regions else "northeurope"
        )
        analysis.suggested_actions = [
            f"Request quota increase for {resource_type} in {current_location}",
            f"Retry deployment in alternative region: {alternative_region}",
            "Consider using smaller resource sizes to reduce quota usage",
            "Review current resource utilization and cleanup unused resources",
        ]

        analysis.estimated_resolution_time_minutes = 30
        analysis.requires_manual_intervention = True

        return analysis

    async def _analyze_configuration_error(
        self, analysis: ErrorAnalysis, error_message: str, context: dict[str, Any]
    ) -> ErrorAnalysis:
        resource_type = context.get("resource_type", "")
        current_sku = context.get("sku", context.get("vm_size", ""))
        location = context.get("location", "westeurope")

        if "sku" in error_message and current_sku:
            sku_category = self._map_resource_to_sku_category(resource_type)
            if sku_category and current_sku in self._sku_alternatives.get(sku_category, {}):
                alternatives = self._sku_alternatives[sku_category][current_sku]
                analysis.alternative_configurations = [
                    {
                        "sku": alt,
                        "resource_type": resource_type,
                        "reason": f"Available alternative to {current_sku} in {location}",
                    }
                    for alt in alternatives[:3]
                ]

        available_sku = (
            analysis.alternative_configurations[0]["sku"]
            if analysis.alternative_configurations
            else "Standard_B1s"
        )
        analysis.suggested_actions = [
            f"Switch to available SKU: {available_sku}",
            f"Verify SKU availability in {location} region",
            "Review resource requirements and select appropriate tier",
            "Check Azure service availability by region documentation",
        ]

        analysis.retry_feasible = True
        analysis.estimated_resolution_time_minutes = 5

        return analysis

    async def _analyze_network_error(
        self, analysis: ErrorAnalysis, error_message: str, context: dict[str, Any]
    ) -> ErrorAnalysis:
        current_cidr = context.get("address_space", context.get("cidr", ""))

        available_cidrs = []
        if current_cidr:
            used_cidrs = [current_cidr]
            available_cidrs = [cidr for cidr in self._network_cidr_pool if cidr not in used_cidrs][
                :3
            ]
        else:
            available_cidrs = self._network_cidr_pool[:3]

        analysis.alternative_configurations = [
            {
                "address_space": cidr,
                "subnet_cidr": self._generate_subnet_cidr(cidr),
                "reason": "Alternative network range to avoid conflicts",
            }
            for cidr in available_cidrs
        ]

        analysis.suggested_actions = [
            (
                f"Use alternative CIDR range: "
                f"{available_cidrs[0] if available_cidrs else '10.1.0.0/16'}"
            ),
            "Verify existing network configurations in target region",
            "Consider using non-overlapping address spaces",
            "Review VNet peering and connectivity requirements",
        ]

        analysis.retry_feasible = True
        analysis.estimated_resolution_time_minutes = 10

        return analysis

    async def _analyze_security_error(
        self, analysis: ErrorAnalysis, error_message: str, context: dict[str, Any]
    ) -> ErrorAnalysis:
        resource_type = context.get("resource_type", "")
        principal_id = context.get("principal_id", "service_principal")

        required_roles = self._get_required_roles(resource_type)

        analysis.suggested_actions = [
            (
                f"Grant '{required_roles[0]}' role to {principal_id}"
                if required_roles
                else "Review service principal permissions"
            ),
            f"Verify subscription-level access for {resource_type} deployment",
            "Check resource group contributor permissions",
            "Ensure service principal is not blocked by conditional access policies",
        ]

        analysis.requires_manual_intervention = True
        analysis.retry_feasible = False
        analysis.estimated_resolution_time_minutes = 20

        return analysis

    async def _analyze_dependency_error(
        self, analysis: ErrorAnalysis, error_message: str, context: dict[str, Any]
    ) -> ErrorAnalysis:
        missing_dependency = self._extract_missing_dependency(error_message)
        resource_type = context.get("resource_type", "")

        analysis.suggested_actions = [
            (
                f"Create missing dependency: {missing_dependency}"
                if missing_dependency
                else "Verify all dependencies exist"
            ),
            f"Check deployment order for {resource_type}",
            "Validate parent resource configurations",
            "Review resource naming consistency",
        ]

        analysis.retry_feasible = True
        analysis.estimated_resolution_time_minutes = 15

        return analysis

    async def _analyze_generic_error(
        self, analysis: ErrorAnalysis, error_message: str, context: dict[str, Any]
    ) -> ErrorAnalysis:
        resource_type = context.get("resource_type", "")
        location = context.get("location", "westeurope")

        analysis.suggested_actions = [
            f"Review {resource_type} configuration parameters",
            f"Verify resource quotas and limits in {location}",
            "Check Azure service health status",
            "Retry deployment with exponential backoff",
        ]

        analysis.retry_feasible = True
        analysis.estimated_resolution_time_minutes = 10

        return analysis

    async def generate_remediation_plan(
        self, analysis: ErrorAnalysis, context: dict[str, Any]
    ) -> RemediationPlan:
        with tracer.start_as_current_span(
            "generate_remediation_plan",
            attributes={
                "error_category": analysis.error_category,
                "severity": analysis.severity,
            },
        ) as span:
            logger.info(
                "Generating intelligent remediation plan",
                error_category=analysis.error_category,
                severity=analysis.severity,
                alternatives_available=len(analysis.alternative_configurations),
            )

            primary_action = (
                analysis.suggested_actions[0]
                if analysis.suggested_actions
                else "Review configuration"
            )
            backup_actions = (
                analysis.suggested_actions[1:] if len(analysis.suggested_actions) > 1 else []
            )

            config_adjustments = {}
            resource_alternatives = []

            if analysis.alternative_configurations:
                config_adjustments = analysis.alternative_configurations[0].copy()
                config_adjustments.pop("reason", None)
                resource_alternatives = analysis.alternative_configurations[1:]

            if analysis.recommended_regions:
                config_adjustments["location"] = analysis.recommended_regions[0]

            success_probability = self._calculate_success_probability(analysis, context)
            execution_order = self._determine_execution_order(analysis, context)

            plan = RemediationPlan(
                primary_action=primary_action,
                backup_actions=backup_actions,
                configuration_adjustments=config_adjustments,
                resource_alternatives=resource_alternatives,
                estimated_success_probability=success_probability,
                execution_order=execution_order,
            )

            span.set_attributes(
                {
                    "primary_action_defined": bool(primary_action),
                    "backup_actions_count": len(backup_actions),
                    "config_adjustments_count": len(config_adjustments),
                    "success_probability": success_probability,
                }
            )

            logger.info(
                "Remediation plan generated",
                primary_action=primary_action,
                backup_actions_count=len(backup_actions),
                success_probability=success_probability,
                requires_manual_intervention=analysis.requires_manual_intervention,
            )

            return plan

    def _map_resource_to_sku_category(self, resource_type: str) -> str | None:
        mapping = {
            "virtual_machine": "virtual_machines",
            "vm": "virtual_machines",
            "app_service": "app_service",
            "webapp": "app_service",
            "storage_account": "storage_account",
            "sql_database": "sql_database",
        }
        return mapping.get(resource_type.lower())

    def _generate_subnet_cidr(self, vnet_cidr: str) -> str:
        if vnet_cidr.endswith("/16"):
            return vnet_cidr.replace("/16", "/24")
        elif vnet_cidr.endswith("/24"):
            return vnet_cidr.replace("/24", "/26")
        else:
            return "10.0.1.0/24"

    def _get_required_roles(self, resource_type: str) -> list[str]:
        role_map = {
            "virtual_machine": ["Virtual Machine Contributor", "Compute Contributor"],
            "storage_account": ["Storage Account Contributor"],
            "app_service": ["Website Contributor", "App Service Contributor"],
            "sql_database": ["SQL DB Contributor", "SQL Server Contributor"],
            "key_vault": ["Key Vault Contributor"],
            "network": ["Network Contributor"],
        }
        return role_map.get(resource_type.lower(), ["Contributor"])

    def _extract_missing_dependency(self, error_message: str) -> str:
        dependency_patterns = [
            (r"resource group '([^']+)' not found", "Resource Group"),
            (r"virtual network '([^']+)' not found", "Virtual Network"),
            (r"subnet '([^']+)' not found", "Subnet"),
            (r"storage account '([^']+)' not found", "Storage Account"),
            (r"key vault '([^']+)' not found", "Key Vault"),
        ]

        for pattern, resource_type in dependency_patterns:
            match = re.search(pattern, error_message, re.IGNORECASE)
            if match:
                return f"{resource_type}: {match.group(1)}"

        return "Unknown dependency"

    def _calculate_success_probability(
        self, analysis: ErrorAnalysis, context: dict[str, Any]
    ) -> float:
        base_probability = 0.7

        if analysis.error_category == "configuration" and analysis.alternative_configurations:
            base_probability = 0.9
        elif analysis.error_category == "capacity" and analysis.recommended_regions:
            base_probability = 0.8
        elif analysis.error_category == "network" and analysis.alternative_configurations:
            base_probability = 0.85
        elif analysis.error_category == "security":
            base_probability = 0.6

        if analysis.requires_manual_intervention:
            base_probability *= 0.8

        if analysis.severity == "high":
            base_probability *= 0.9

        return min(base_probability, 1.0)

    def _determine_execution_order(
        self, analysis: ErrorAnalysis, context: dict[str, Any]
    ) -> list[str]:
        if analysis.error_category == "capacity":
            return ["adjust_resource_size", "try_alternative_region", "request_quota_increase"]
        elif analysis.error_category == "configuration":
            return ["update_configuration", "validate_parameters", "retry_deployment"]
        elif analysis.error_category == "network":
            return ["adjust_network_config", "validate_connectivity", "retry_deployment"]
        elif analysis.error_category == "security":
            return ["verify_permissions", "update_rbac", "retry_deployment"]
        elif analysis.error_category == "dependency":
            return ["create_dependencies", "validate_order", "retry_deployment"]
        else:
            return ["analyze_logs", "adjust_configuration", "retry_deployment"]
