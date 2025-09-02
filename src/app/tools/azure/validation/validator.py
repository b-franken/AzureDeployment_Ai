from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol


class ValidationLevel(Enum):
    BASIC = "basic"
    STANDARD = "standard"
    STRICT = "strict"
    ENTERPRISE = "enterprise"


class ValidationCategory(Enum):
    NAMING = "naming"
    SECURITY = "security"
    NETWORKING = "networking"
    COMPLIANCE = "compliance"
    COST = "cost"
    PERFORMANCE = "performance"
    AVAILABILITY = "availability"
    TAGS = "tags"
    DEPENDENCIES = "dependencies"
    QUOTAS = "quotas"


@dataclass
class ValidationRule:
    id: str
    category: ValidationCategory
    level: ValidationLevel
    name: str
    description: str
    severity: str
    validator: Callable[
        [dict[str, Any], dict[str, Any]],
        Awaitable[ValidationResult],
    ]
    auto_fix: (
        Callable[
            [dict[str, Any], dict[str, Any]],
            Awaitable[dict[str, Any] | None],
        ]
        | None
    ) = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    rule_id: str
    passed: bool
    message: str
    severity: str
    category: ValidationCategory
    details: dict[str, Any] = field(default_factory=dict)
    fix_available: bool = False
    fix_applied: bool = False


@dataclass
class ValidationReport:
    deployment_id: str
    timestamp: datetime
    level: ValidationLevel
    total_rules: int
    passed_rules: int
    failed_rules: int
    warnings: int
    errors: int
    critical: int
    results: list[ValidationResult]
    summary: dict[str, Any]
    recommendations: list[str]
    auto_fixes_applied: int = 0


class ResourceValidator(Protocol):
    async def validate(
        self, resource: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult: ...


class DeploymentValidator:
    def __init__(self, level: ValidationLevel = ValidationLevel.STANDARD):
        self.level = level
        self.rules: dict[str, ValidationRule] = {}
        self._initialize_rules()

    def _initialize_rules(self) -> None:
        self.rules["naming_convention"] = ValidationRule(
            id="naming_convention",
            category=ValidationCategory.NAMING,
            level=ValidationLevel.BASIC,
            name="Resource Naming Convention",
            description="Validates resource names against Azure naming conventions",
            severity="warning",
            validator=self._validate_naming_convention,
            auto_fix=self._fix_naming_convention,
        )

        self.rules["mandatory_tags"] = ValidationRule(
            id="mandatory_tags",
            category=ValidationCategory.TAGS,
            level=ValidationLevel.STANDARD,
            name="Mandatory Tags",
            description="Ensures required tags are present",
            severity="error",
            validator=self._validate_mandatory_tags,
            auto_fix=self._fix_mandatory_tags,
        )

        self.rules["network_security"] = ValidationRule(
            id="network_security",
            category=ValidationCategory.SECURITY,
            level=ValidationLevel.STANDARD,
            name="Network Security",
            description="Validates network security configurations",
            severity="critical",
            validator=self._validate_network_security,
        )

        self.rules["encryption_at_rest"] = ValidationRule(
            id="encryption_at_rest",
            category=ValidationCategory.SECURITY,
            level=ValidationLevel.STRICT,
            name="Encryption at Rest",
            description="Ensures encryption at rest is enabled",
            severity="critical",
            validator=self._validate_encryption_at_rest,
        )

        self.rules["backup_configuration"] = ValidationRule(
            id="backup_configuration",
            category=ValidationCategory.AVAILABILITY,
            level=ValidationLevel.ENTERPRISE,
            name="Backup Configuration",
            description="Validates backup configurations",
            severity="error",
            validator=self._validate_backup_configuration,
        )

        self.rules["cost_optimization"] = ValidationRule(
            id="cost_optimization",
            category=ValidationCategory.COST,
            level=ValidationLevel.STANDARD,
            name="Cost Optimization",
            description="Checks for cost optimization opportunities",
            severity="warning",
            validator=self._validate_cost_optimization,
        )

        self.rules["dependency_check"] = ValidationRule(
            id="dependency_check",
            category=ValidationCategory.DEPENDENCIES,
            level=ValidationLevel.BASIC,
            name="Dependency Check",
            description="Validates resource dependencies",
            severity="error",
            validator=self._validate_dependencies,
        )

        self.rules["quota_limits"] = ValidationRule(
            id="quota_limits",
            category=ValidationCategory.QUOTAS,
            level=ValidationLevel.STANDARD,
            name="Quota Limits",
            description="Checks against subscription quotas",
            severity="error",
            validator=self._validate_quota_limits,
        )

    async def validate_deployment(
        self, resources: list[dict[str, Any]], context: dict[str, Any]
    ) -> ValidationReport:
        deployment_id = context.get("deployment_id", "unknown")
        results: list[ValidationResult] = []

        applicable_rules = self._get_applicable_rules()

        for rule in applicable_rules.values():
            for resource in resources:
                result = await rule.validator(resource, context)
                result.rule_id = rule.id
                result.category = rule.category
                result.severity = rule.severity

                if not result.passed and rule.auto_fix and context.get("auto_fix", False):
                    fixed_resource = await rule.auto_fix(resource, context)
                    if fixed_resource:
                        resource.update(fixed_resource)
                        result.fix_applied = True

                results.append(result)

        report = self._generate_report(deployment_id, results, applicable_rules)
        return report

    def _get_applicable_rules(self) -> dict[str, ValidationRule]:
        level_priority = {
            ValidationLevel.BASIC: 1,
            ValidationLevel.STANDARD: 2,
            ValidationLevel.STRICT: 3,
            ValidationLevel.ENTERPRISE: 4,
        }

        current_priority = level_priority.get(self.level, 2)

        return {
            rule_id: rule
            for rule_id, rule in self.rules.items()
            if level_priority.get(rule.level, 1) <= current_priority
        }

    def _generate_report(
        self,
        deployment_id: str,
        results: list[ValidationResult],
        rules: dict[str, ValidationRule],
    ) -> ValidationReport:
        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]

        severity_counts = {
            "warning": len([r for r in failed if r.severity == "warning"]),
            "error": len([r for r in failed if r.severity == "error"]),
            "critical": len([r for r in failed if r.severity == "critical"]),
        }

        category_summary: dict[str, Any] = {}
        for category in ValidationCategory:
            category_results = [r for r in results if r.category == category]
            if category_results:
                category_summary[category.value] = {
                    "total": len(category_results),
                    "passed": len([r for r in category_results if r.passed]),
                    "failed": len([r for r in category_results if not r.passed]),
                }

        recommendations = self._generate_recommendations(failed)

        return ValidationReport(
            deployment_id=deployment_id,
            timestamp=datetime.utcnow(),
            level=self.level,
            total_rules=len(results),
            passed_rules=len(passed),
            failed_rules=len(failed),
            warnings=severity_counts["warning"],
            errors=severity_counts["error"],
            critical=severity_counts["critical"],
            results=results,
            summary=category_summary,
            recommendations=recommendations,
            auto_fixes_applied=len([r for r in results if r.fix_applied]),
        )

    def _generate_recommendations(self, failed_results: list[ValidationResult]) -> list[str]:
        recommendations: list[str] = []

        critical_issues = [r for r in failed_results if r.severity == "critical"]
        if critical_issues:
            recommendations.append("Address critical security issues before deployment")

        security_issues = [r for r in failed_results if r.category == ValidationCategory.SECURITY]
        if len(security_issues) > 3:
            recommendations.append("Review and strengthen security configurations")

        cost_issues = [r for r in failed_results if r.category == ValidationCategory.COST]
        if cost_issues:
            recommendations.append("Consider cost optimization recommendations to reduce expenses")

        return recommendations

    async def _validate_naming_convention(
        self, resource: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        name = resource.get("name", "")
        resource_type = resource.get("type", "")

        patterns = {
            "Microsoft.Compute/virtualMachines": r"^vm-[a-z0-9]{1,15}$",
            "Microsoft.Storage/storageAccounts": r"^st[a-z0-9]{3,22}$",
            "Microsoft.Network/virtualNetworks": r"^vnet-[a-z0-9-]{1,20}$",
            "Microsoft.Web/sites": r"^app-[a-z0-9-]{1,20}$",
        }

        pattern = patterns.get(resource_type)
        if not pattern:
            return ValidationResult(
                rule_id="naming_convention",
                passed=True,
                message="No naming convention defined for resource type",
                severity="info",
                category=ValidationCategory.NAMING,
            )

        if re.match(pattern, name):
            return ValidationResult(
                rule_id="naming_convention",
                passed=True,
                message="Naming convention validated",
                severity="info",
                category=ValidationCategory.NAMING,
            )

        return ValidationResult(
            rule_id="naming_convention",
            passed=False,
            message=f"Name '{name}' does not match pattern '{pattern}'",
            severity="warning",
            category=ValidationCategory.NAMING,
            fix_available=True,
        )

    async def _fix_naming_convention(
        self, resource: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        resource_type = resource.get("type", "")

        prefixes = {
            "Microsoft.Compute/virtualMachines": "vm",
            "Microsoft.Storage/storageAccounts": "st",
            "Microsoft.Network/virtualNetworks": "vnet",
            "Microsoft.Web/sites": "app",
        }

        prefix = prefixes.get(resource_type, "res")
        env = context.get("environment", "dev")
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M")[:8]

        new_name = f"{prefix}-{env}-{timestamp}"
        resource["name"] = new_name

        return resource

    async def _validate_mandatory_tags(
        self, resource: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        required_tags = ["environment", "owner", "cost-center", "project"]
        tags = resource.get("tags", {})

        missing_tags = [tag for tag in required_tags if tag not in tags]

        if not missing_tags:
            return ValidationResult(
                rule_id="mandatory_tags",
                passed=True,
                message="All mandatory tags present",
                severity="info",
                category=ValidationCategory.TAGS,
            )

        return ValidationResult(
            rule_id="mandatory_tags",
            passed=False,
            message=f"Missing tags: {', '.join(missing_tags)}",
            severity="error",
            category=ValidationCategory.TAGS,
            details={"missing_tags": missing_tags},
            fix_available=True,
        )

    async def _fix_mandatory_tags(
        self, resource: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        if "tags" not in resource:
            resource["tags"] = {}

        defaults = {
            "environment": context.get("environment", "dev"),
            "owner": context.get("initiated_by", "unknown"),
            "cost-center": context.get("cost_center", "default"),
            "project": context.get("project", "default"),
        }

        for tag, value in defaults.items():
            if tag not in resource["tags"]:
                resource["tags"][tag] = value

        return resource

    async def _validate_network_security(
        self, resource: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        resource_type = resource.get("type", "")

        if resource_type not in [
            "Microsoft.Network/networkSecurityGroups",
            "Microsoft.Compute/virtualMachines",
        ]:
            return ValidationResult(
                rule_id="network_security",
                passed=True,
                message="Not applicable to resource type",
                severity="info",
                category=ValidationCategory.SECURITY,
            )

        issues: list[str] = []

        if resource_type == "Microsoft.Network/networkSecurityGroups":
            rules = resource.get("properties", {}).get("securityRules", [])
            for rule in rules:
                if rule.get("destinationPortRange") == "*":
                    issues.append(f"Rule {rule.get('name')} allows all ports")
                if rule.get("sourceAddressPrefix") == "*":
                    issues.append(f"Rule {rule.get('name')} allows all source IPs")

        if issues:
            return ValidationResult(
                rule_id="network_security",
                passed=False,
                message="Security issues detected",
                severity="critical",
                category=ValidationCategory.SECURITY,
                details={"issues": issues},
            )

        return ValidationResult(
            rule_id="network_security",
            passed=True,
            message="Network security validated",
            severity="info",
            category=ValidationCategory.SECURITY,
        )

    async def _validate_encryption_at_rest(
        self, resource: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        resource_type = resource.get("type", "")
        properties = resource.get("properties", {})

        encryption_checks: dict[str, Callable[[dict[str, Any]], bool]] = {
            "Microsoft.Storage/storageAccounts": lambda p: bool(
                p.get("encryption", {}).get("services", {}).get("blob", {}).get("enabled")
            ),
            "Microsoft.Sql/servers/databases": lambda p: p.get("transparentDataEncryption", {}).get(
                "status"
            )
            == "Enabled",
            "Microsoft.Compute/disks": lambda p: p.get("encryption", {}).get("type")
            != "EncryptionAtRestWithPlatformKey",
        }

        check = encryption_checks.get(resource_type)
        if not check:
            return ValidationResult(
                rule_id="encryption_at_rest",
                passed=True,
                message="Not applicable to resource type",
                severity="info",
                category=ValidationCategory.SECURITY,
            )

        if check(properties):
            return ValidationResult(
                rule_id="encryption_at_rest",
                passed=True,
                message="Encryption at rest enabled",
                severity="info",
                category=ValidationCategory.SECURITY,
            )

        return ValidationResult(
            rule_id="encryption_at_rest",
            passed=False,
            message="Encryption at rest not properly configured",
            severity="critical",
            category=ValidationCategory.SECURITY,
        )

    async def _validate_backup_configuration(
        self, resource: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        resource_type = resource.get("type", "")

        backup_required = [
            "Microsoft.Compute/virtualMachines",
            "Microsoft.Sql/servers/databases",
            "Microsoft.Storage/storageAccounts",
        ]

        if resource_type not in backup_required:
            return ValidationResult(
                rule_id="backup_configuration",
                passed=True,
                message="Backup not required for resource type",
                severity="info",
                category=ValidationCategory.AVAILABILITY,
            )

        backup_config = resource.get("properties", {}).get("backupConfiguration")
        if backup_config:
            return ValidationResult(
                rule_id="backup_configuration",
                passed=True,
                message="Backup configured",
                severity="info",
                category=ValidationCategory.AVAILABILITY,
            )

        return ValidationResult(
            rule_id="backup_configuration",
            passed=False,
            message="Backup not configured for critical resource",
            severity="error",
            category=ValidationCategory.AVAILABILITY,
        )

    async def _validate_cost_optimization(
        self, resource: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        resource_type = resource.get("type", "")
        recommendations: list[str] = []

        if resource_type == "Microsoft.Compute/virtualMachines":
            size = resource.get("properties", {}).get("hardwareProfile", {}).get("vmSize", "")
            if "Standard_D" in size and context.get("environment") == "dev":
                recommendations.append("Consider B-series VMs for dev environment")

        if resource_type == "Microsoft.Storage/storageAccounts":
            tier = resource.get("properties", {}).get("accessTier", "")
            if tier == "Hot" and context.get("environment") == "dev":
                recommendations.append("Consider Cool tier for dev storage")

        if recommendations:
            return ValidationResult(
                rule_id="cost_optimization",
                passed=False,
                message="Cost optimization opportunities found",
                severity="warning",
                category=ValidationCategory.COST,
                details={"recommendations": recommendations},
            )

        return ValidationResult(
            rule_id="cost_optimization",
            passed=True,
            message="No cost optimization issues found",
            severity="info",
            category=ValidationCategory.COST,
        )

    async def _validate_dependencies(
        self, resource: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        dependencies = resource.get("dependsOn", [])
        all_resources = context.get("all_resources", [])
        resource_ids = [r.get("id") for r in all_resources if r.get("id")]

        missing_deps = [dep for dep in dependencies if dep not in resource_ids]

        if missing_deps:
            return ValidationResult(
                rule_id="dependency_check",
                passed=False,
                message="Missing dependencies",
                severity="error",
                category=ValidationCategory.DEPENDENCIES,
                details={"missing": missing_deps},
            )

        return ValidationResult(
            rule_id="dependency_check",
            passed=True,
            message="All dependencies satisfied",
            severity="info",
            category=ValidationCategory.DEPENDENCIES,
        )

    async def _validate_quota_limits(
        self, resource: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        resource_type = resource.get("type", "")
        location = resource.get("location", "")

        quotas = context.get("subscription_quotas", {})
        resource_quotas = quotas.get(resource_type, {}).get(location, {})

        if not resource_quotas:
            return ValidationResult(
                rule_id="quota_limits",
                passed=True,
                message="No quota information available",
                severity="info",
                category=ValidationCategory.QUOTAS,
            )

        current_usage = resource_quotas.get("current", 0)
        limit = resource_quotas.get("limit", float("inf"))

        if current_usage >= limit:
            return ValidationResult(
                rule_id="quota_limits",
                passed=False,
                message=f"Quota limit reached: {current_usage}/{limit}",
                severity="error",
                category=ValidationCategory.QUOTAS,
                details={"current": current_usage, "limit": limit},
            )

        return ValidationResult(
            rule_id="quota_limits",
            passed=True,
            message=f"Within quota limits: {current_usage}/{limit}",
            severity="info",
            category=ValidationCategory.QUOTAS,
        )
