from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DeploymentIntent(Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SCALE = "scale"
    BACKUP = "backup"
    RESTORE = "restore"
    MIGRATE = "migrate"
    MONITOR = "monitor"
    SECURE = "secure"
    OPTIMIZE = "optimize"
    VALIDATE = "validate"
    COST_ANALYZE = "cost_analyze"
    DRIFT_CHECK = "drift_check"
    ROLLBACK = "rollback"


@dataclass
class ParsedIntent:
    intent: DeploymentIntent
    confidence: float
    resource_type: str
    attributes: dict[str, object]
    dependencies: list[str]
    compliance_requirements: list[str]
    cost_optimization_hints: list[str]
    resource_name: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    validation_rules: list[str] = field(default_factory=list)
    cost_constraints: dict[str, Any] = field(default_factory=dict)
    deployment_strategy: str = "direct"


class EnterpriseNLPParser:
    def __init__(self) -> None:
        self.intent_patterns: dict[DeploymentIntent, list[str]] = {
            DeploymentIntent.CREATE: [
                (
                    r"\b("
                    r"create|deploy|provision|setup|establish|build|launch|"
                    r"instantiate|spin up|stand up|bring up|set up"
                    r")\b"
                ),
                (
                    r"\b("
                    r"need|want|require|should have|must have"
                    r")\b.*\b("
                    r"new|fresh|initial"
                    r")\b"
                ),
            ],
            DeploymentIntent.UPDATE: [
                (
                    r"\b("
                    r"update|modify|change|alter|adjust|reconfigure|patch|upgrade|"
                    r"downgrade|resize|expand|enhance|improve|optimize"
                    r")\b"
                )
            ],
            DeploymentIntent.DELETE: [
                (
                    r"\b("
                    r"delete|remove|destroy|terminate|decommission|tear down|"
                    r"clean up|purge|dispose|wipe|eliminate"
                    r")\b"
                )
            ],
            DeploymentIntent.SCALE: [
                (r"\b(" r"scale|resize|expand|contract|grow|shrink|autoscale" r")\b"),
                (
                    r"\b("
                    r"increase|decrease|add more|reduce"
                    r")\b.*\b("
                    r"capacity|nodes|instances|replicas"
                    r")\b"
                ),
            ],
            DeploymentIntent.BACKUP: [
                r"\b("
                r"backup|snapshot|archive|preserve|save state|create backup"
                r")\b"
            ],
            DeploymentIntent.RESTORE: [r"\b(restore|recover|rollback|revert|undo)\b"],
            DeploymentIntent.MIGRATE: [r"\b(migrate|move|transfer|relocate|shift)\b"],
            DeploymentIntent.MONITOR: [
                r"\b(" r"monitor|watch|track|observe|alert on|set alerts" r")\b"
            ],
            DeploymentIntent.SECURE: [
                r"\b(" r"secure|harden|protect|encrypt|lock down|enable security" r")\b"
            ],
            DeploymentIntent.OPTIMIZE: [
                (
                    r"\b("
                    r"optimize|tune|improve performance|reduce cost|minimize expense|"
                    r"cost optimization"
                    r")\b"
                )
            ],
            DeploymentIntent.VALIDATE: [
                r"\b(validate|check|verify|test|ensure|confirm)\b"
            ],
            DeploymentIntent.COST_ANALYZE: [
                (
                    r"\b("
                    r"cost analysis|analyze cost|spending|budget|forecast|"
                    r"cost optimization"
                    r")\b"
                )
            ],
            DeploymentIntent.DRIFT_CHECK: [
                r"\b(drift|configuration drift|check drift|detect changes)\b"
            ],
            DeploymentIntent.ROLLBACK: [
                r"\b(rollback|revert|undo deployment|previous version)\b"
            ],
        }

        self.resource_patterns: dict[str, list[str]] = {
            "aks_cluster": [
                (
                    r"\b("
                    r"kubernetes|k8s|aks|container orchestration|microservices platform"
                    r")\b"
                ),
                (r"\b(" r"container cluster|k8s cluster|managed kubernetes" r")\b"),
            ],
            "container_registry": [
                (
                    r"\b("
                    r"container registry|docker registry|acr|image repository"
                    r")\b"
                ),
                (r"\b(" r"docker hub alternative|private registry" r")\b"),
            ],
            "webapp": [
                (r"\b(" r"web app|webapp|app service|website|web application" r")\b"),
            ],
            "function_app": [
                (
                    r"\b("
                    r"function app|serverless function|azure function|lambda"
                    r")\b"
                ),
            ],
            "storage_account": [
                (r"\b(" r"storage account|blob storage|file storage|data lake" r")\b"),
            ],
            "database": [
                (r"\b(" r"database|sql|cosmos|postgresql|mysql|mongodb|mongo" r")\b"),
            ],
            "virtual_machine": [
                (r"\b(" r"virtual machine|vm|server|compute instance|compute" r")\b"),
            ],
            "network": [
                (
                    r"\b("
                    r"network|vnet|subnet|firewall|load balancer|application gateway"
                    r")\b"
                ),
            ],
            "keyvault": [
                (
                    r"\b("
                    r"key vault|keyvault|secrets|certificates|keys management|certificates store"
                    r")\b"
                ),
            ],
            "api_management": [
                (r"\b(" r"api management|apim|api gateway|api proxy" r")\b"),
                (r"\b(" r"api orchestration|api facade" r")\b"),
            ],
            "service_bus": [
                (
                    r"\b("
                    r"service bus|message queue|messaging|enterprise messaging"
                    r")\b"
                ),
                r"\b(queue service|topic subscription)\b",
            ],
            "event_hub": [
                (
                    r"\b("
                    r"event hub|streaming|event streaming|kafka|message streaming|"
                    r"event ingestion"
                    r")\b"
                ),
            ],
            "cognitive_services": [
                (
                    r"\b("
                    r"cognitive services|ai services|ml services|vision|speech|"
                    r"language"
                    r")\b"
                ),
            ],
            "data_factory": [
                (
                    r"\b("
                    r"data factory|etl|data pipeline|data integration|"
                    r"data orchestration|data workflow"
                    r")\b"
                ),
            ],
            "synapse": [
                (
                    r"\b("
                    r"synapse|data warehouse|analytics workspace|big data|"
                    r"data lake analytics"
                    r")\b"
                ),
            ],
            "front_door": [
                (
                    r"\b("
                    r"front door|global load balancer|cdn|content delivery|"
                    r"global routing|edge optimization"
                    r")\b"
                ),
            ],
            "redis": [
                (r"\b(" r"redis|cache|azure cache|memory cache" r")\b"),
            ],
            "logic_apps": [
                (
                    r"\b("
                    r"logic apps|workflow automation|business process|"
                    r"integration workflow|automated workflow"
                    r")\b"
                ),
            ],
            "container_instances": [
                (
                    r"\b("
                    r"container instances|aci|containers without orchestration"
                    r")\b"
                ),
            ],
            "batch": [
                (
                    r"\b("
                    r"batch|batch processing|hpc|high performance computing"
                    r")\b"
                ),
            ],
        }

        self.basic_resource_fallbacks: dict[str, str] = {
            "storage": r"\b(storage|blob|file share|data lake)\b",
            "webapp": r"\b(web app|website|app service|web application)\b",
            "database": r"\b(database|sql|cosmos|mongo|postgresql|mysql)\b",
            "vm": r"\b(virtual machine|vm|server|compute)\b",
            "network": r"\b(network|vnet|subnet|firewall|load balancer)\b",
            "keyvault": r"\b(key vault|keyvault|secrets|certificates)\b",
        }

        self.compliance_patterns: dict[str, list[str]] = {
            "gdpr": [r"\b(gdpr|european data|eu compliance)\b"],
            "hipaa": [r"\b(hipaa|healthcare|medical data|phi)\b"],
            "pci_dss": [r"\b(pci-?dss|payment card|credit card|payment compliance)\b"],
            "sox": [r"\b(sox|sarbanes|financial compliance)\b"],
            "iso27001": [r"\b(iso-?27001|information security)\b"],
            "fedramp": [r"\b(fedramp|federal|government compliance)\b"],
        }

        self.environment_indicators: dict[str, list[str]] = {
            "production": [r"\b(prod|production|live|main)\b"],
            "staging": [r"\b(staging|stage|uat|pre-?prod)\b"],
            "development": [r"\b(dev|development)\b"],
            "test": [r"\b(test|testing|qa)\b"],
            "disaster_recovery": [r"\b(dr|disaster recovery|backup site)\b"],
        }

        self.sizing_patterns: dict[str, list[str]] = {
            "small": [r"\b(small|minimal|basic|starter|lightweight)\b"],
            "medium": [r"\b(medium|standard|moderate|balanced)\b"],
            "large": [r"\b(large|heavy|substantial|significant)\b"],
            "xlarge": [r"\b(extra large|xl|very large|massive|enterprise)\b"],
        }

        self.context_extractors: dict[str, dict[str, Any]] = {
            "location": {
                "patterns": [
                    r"\b(?:in|at|to|for)\s+(west\s*europe|westeurope|north\s*europe|northeurope|uk\s*south|uksouth|east\s*us|eastus|west\s*us|westus|central\s*us|centralus|south\s*east\s*asia|southeastasia)\b"
                ],
                "default": "westeurope",
            },
            "environment": {
                "patterns": [
                    r"\b(dev|development|test|testing|staging|stage|uat|prod|production)\b(?:\s*environment)?"
                ],
                "default": "development",
            },
            "subscription": {
                "patterns": [r"subscription\s+(?:id\s+)?([a-f0-9-]{36})"],
                "default": None,
            },
            "resource_group": {
                "patterns": [
                    r"resource\s+group\s+([a-z0-9][\w-]{0,89})",
                    r"rg\s+([a-z0-9][\w-]{0,89})",
                ],
                "default": None,
            },
            "project": {
                "patterns": [r"(?:project|application|app)\s+([a-z0-9][\w-]{0,59})"],
                "default": None,
            },
            "owner": {
                "patterns": [
                    r"(?:owner|owned by|managed by)\s+([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})"
                ],
                "default": None,
            },
            "cost_limit": {
                "patterns": [
                    r"(?:cost limit|budget|max cost|spend limit)\s*(?:of\s+)?\$?(\d+)"
                ],
                "default": None,
            },
        }

        self.validation_rule_sets: dict[str, list[str]] = {
            "naming": [
                "resource_name_length",
                "resource_name_format",
                "unique_name_check",
                "naming_convention_compliance",
            ],
            "security": [
                "encryption_at_rest",
                "encryption_in_transit",
                "network_isolation",
                "identity_management",
                "key_rotation",
                "audit_logging",
            ],
            "compliance": [
                "data_residency",
                "retention_policies",
                "access_controls",
                "audit_trail",
                "regulatory_requirements",
            ],
            "cost": [
                "budget_constraints",
                "cost_optimization",
                "reserved_instances",
                "auto_shutdown",
                "rightsizing",
            ],
            "availability": [
                "sla_requirements",
                "backup_strategy",
                "disaster_recovery",
                "failover_configuration",
                "health_checks",
            ],
            "performance": [
                "scaling_configuration",
                "load_balancing",
                "caching_strategy",
                "cdn_configuration",
                "database_optimization",
            ],
        }

    def parse(self, text: str) -> ParsedIntent:
        t = text.lower().strip()
        intent = self._detect_intent(t)
        resource_type = self._detect_resource_type(t)
        resource_name = self._extract_resource_name(t, resource_type)
        attributes = self._extract_attributes(t)
        context = self._extract_context(t)
        dependencies = self._detect_dependencies(t)
        compliance = self._detect_compliance_requirements(t)
        cost_hints = self._extract_cost_optimization_hints(t)
        cost_constraints = self._extract_cost_constraints(t)
        validation_rules = self._determine_validation_rules(
            resource_type, context, attributes, cost_constraints, compliance
        )
        deployment_strategy = self._determine_deployment_strategy(
            intent, context, attributes
        )
        confidence = self._calculate_confidence(t, intent, resource_type, context)
        return ParsedIntent(
            intent=intent,
            confidence=confidence,
            resource_type=resource_type,
            attributes=attributes,
            dependencies=dependencies,
            compliance_requirements=compliance,
            cost_optimization_hints=cost_hints,
            resource_name=resource_name,
            context=context,
            validation_rules=validation_rules,
            cost_constraints=cost_constraints,
            deployment_strategy=deployment_strategy,
        )

    def _detect_intent(self, text: str) -> DeploymentIntent:
        scores: dict[DeploymentIntent, int] = {}
        for intent, patterns in self.intent_patterns.items():
            score = 0
            for p in patterns:
                if re.search(p, text):
                    score += 2
            scores[intent] = score
        if not scores or max(scores.values()) == 0:
            return DeploymentIntent.CREATE
        return max(scores, key=lambda k: scores[k])

    def _detect_resource_type(self, text: str) -> str:
        for r, patterns in self.resource_patterns.items():
            for p in patterns:
                if re.search(p, text):
                    return r
        for r, p in self.basic_resource_fallbacks.items():
            if re.search(p, text):
                return r
        return "generic"

    def _extract_resource_name(self, text: str, resource_type: str) -> str | None:
        if resource_type == "generic":
            return None
        patterns = [
            rf"{resource_type}\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{{0,79}})",
            rf"(?:create|deploy|provision)\s+(?:a\s+)?{resource_type}\s+([a-z0-9][\w-]{{0,79}})",
            rf"([a-z0-9][\w-]{{2,79}})\s+{resource_type}",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    def _extract_attributes(self, text: str) -> dict[str, object]:
        a: dict[str, object] = {}
        env = self._match_first(text, self.environment_indicators)
        if env:
            a["environment"] = env
        size = self._match_first(text, self.sizing_patterns)
        if size:
            a["sizing"] = size
        geo_patterns: dict[str, list[str]] = {
            "multi_region": [r"\b(multi-region|multi region|global|worldwide)\b"],
            "single_region": [r"\b(single region|regional|local)\b"],
        }
        geo = self._match_first(text, geo_patterns)
        if geo:
            a["geo_redundancy"] = geo
        terms = (
            "high availability",
            "ha",
            "highly available",
            "redundant",
            "fault tolerant",
            "multi-zone",
            "zone redundant",
        )
        pattern = r"\b(" + "|".join(terms) + r")\b"
        if re.search(pattern, text):
            a["high_availability"] = True
        if re.search(r"\b(disaster recovery|dr|backup region|failover)\b", text):
            a["disaster_recovery"] = True
        if re.search(r"\b(auto scale|autoscale|automatic scaling|elastic)\b", text):
            a["autoscaling"] = True
        if re.search(r"\b(managed identity|msi|system assigned|user assigned)\b", text):
            a["managed_identity"] = True
        if re.search(r"\b(private endpoint|private link|internal only)\b", text):
            a["private_endpoints"] = True
        if re.search(
            r"\b(with backup|backup enabled|enable backup|daily backup|automated backup)\b",
            text,
        ):
            a["backup"] = True
        if re.search(
            r"\b(with monitoring|monitoring enabled|enable monitoring|"
            r"application insights|log analytics)\b",
            text,
        ):
            a["monitoring"] = True
        return a

    def _extract_context(self, text: str) -> dict[str, Any]:
        def pick(cfg: dict[str, Any]) -> str | None:
            for p in cfg["patterns"]:
                m = re.search(p, text, re.IGNORECASE)
                if m and m.groups():
                    return m.group(1)
            return cfg.get("default")

        location = pick(self.context_extractors["location"]) or "westeurope"
        environment = pick(self.context_extractors["environment"]) or "development"
        subscription = pick(self.context_extractors["subscription"])
        resource_group = pick(self.context_extractors["resource_group"])
        tags: dict[str, str] = {
            "environment": environment,
            "managed_by": "devops-ai",
            "created_date": datetime.utcnow().isoformat(),
        }
        project = pick(self.context_extractors["project"])
        if project:
            tags["project"] = project
        owner = pick(self.context_extractors["owner"])
        if owner:
            tags["owner"] = owner
        compliance = []
        for k, patterns in self.compliance_patterns.items():
            for p in patterns:
                if re.search(p, text, re.IGNORECASE):
                    compliance.append(k)
                    break

        networking: dict[str, Any] = {}
        if "private endpoint" in text or "private link" in text:
            networking["private_endpoints"] = True
        vm = re.search(r"vnet\s+([a-z0-9][\w-]{0,59})", text, re.IGNORECASE)
        if vm:
            networking["vnet_name"] = vm.group(1)
        sm = re.search(r"subnet\s+([a-z0-9][\w-]{0,59})", text, re.IGNORECASE)
        if sm:
            networking["subnet_name"] = sm.group(1)
        if "nsg" in text or "network security group" in text:
            networking["network_security_group"] = True
        if "load balancer" in text:
            networking["load_balancer"] = True
        if "application gateway" in text:
            networking["application_gateway"] = True

        security: dict[str, Any] = {}
        if "managed identity" in text or "msi" in text:
            security["managed_identity"] = True
        if "key vault" in text or "keyvault" in text:
            security["key_vault_integration"] = True
        if "encryption" in text:
            security["encryption_at_rest"] = True
            security["encryption_in_transit"] = True
        if "firewall" in text:
            security["firewall_enabled"] = True
        if "private" in text and "public" not in text:
            security["public_access"] = False
        if "rbac" in text or "role based" in text:
            security["rbac_enabled"] = True
        if "audit" in text or "logging" in text:
            security["audit_logging"] = True

        backup: dict[str, Any] = {}
        if "backup" in text:
            backup["enabled"] = True
            if "daily" in text:
                backup["frequency"] = "daily"
            elif "weekly" in text:
                backup["frequency"] = "weekly"
            elif "monthly" in text:
                backup["frequency"] = "monthly"
            else:
                backup["frequency"] = "daily"
            rm = re.search(r"(\d+)\s*day", text, re.IGNORECASE)
            backup["retention_days"] = int(rm.group(1)) if rm else 30
            if "geo-redundant" in text or "grs" in text:
                backup["geo_redundant"] = True

        ctx: dict[str, Any] = {
            "provider": "azure",
            "subscription_id": subscription or "",
            "resource_group": resource_group or f"{environment}-rg",
            "location": location,
            "environment": environment,
            "tags": tags,
            "compliance_framework": compliance,
            "networking_config": networking,
            "security_config": security,
            "backup_config": backup,
        }
        return ctx

    def _detect_dependencies(self, text: str) -> list[str]:
        deps: list[str] = []
        patterns: dict[str, str] = {
            "active_directory": (
                r"\b(active directory|azure ad|aad|identity provider|"
                r"authentication)\b"
            ),
            "dns": (r"\b(dns|domain|custom domain|hostname|a record|cname)\b"),
            "certificate": (r"\b(certificate|ssl|tls|https|cert manager)\b"),
            "monitoring": (
                r"\b(monitoring|application insights|log analytics|"
                r"alerts|metrics)\b"
            ),
            "backup": (r"\b(backup|restore|recovery|snapshot|disaster recovery)\b"),
            "networking": (
                r"\b(existing network|vnet|subnet|network integration|peering)\b"
            ),
            "storage": (r"\b(storage account|blob|file share|data lake)\b"),
            "database": (r"\b(database|sql|cosmos|postgresql|mysql)\b"),
            "container_registry": (r"\b(container registry|acr|docker registry)\b"),
            "key_vault": (r"\b(key vault|keyvault|secrets|certificates store)\b"),
        }
        for k, p in patterns.items():
            if re.search(p, text, re.IGNORECASE):
                deps.append(k)
        return deps

    def _detect_compliance_requirements(self, text: str) -> list[str]:
        out: list[str] = []
        for k, patterns in self.compliance_patterns.items():
            for p in patterns:
                if re.search(p, text):
                    out.append(k)
                    break
        return out

    def _extract_cost_optimization_hints(self, text: str) -> list[str]:
        hints: list[str] = []
        cost_patterns: dict[str, str] = {
            "use_spot_instances": r"\b(spot instance|spot vm|preemptible|low priority)\b",
            "use_reserved_instances": r"\b(reserved|reservation|committed use)\b",
            "auto_shutdown": r"\b(auto shutdown|scheduled shutdown|stop at night)\b",
            "use_serverless": r"\b(serverless|consumption plan|pay per use)\b",
            "optimize_storage_tiers": r"\b(archive|cool storage|storage tier)\b",
            "right_sizing": r"\b(right size|optimize size|cost effective size)\b",
        }
        for k, p in cost_patterns.items():
            if re.search(p, text):
                hints.append(k)
        return hints

    def _extract_cost_constraints(self, text: str) -> dict[str, Any]:
        c: dict[str, Any] = {}
        m = re.search(
            r"(?:cost limit|budget|max cost|spend limit)\s*(?:of\s+)?\$?(\d+)",
            text,
            re.IGNORECASE,
        )
        if m:
            c["monthly_limit"] = float(m.group(1))
        if (
            "minimize cost" in text
            or "cost optimization" in text
            or "reduce cost" in text
        ):
            c["optimize"] = True
        if "spot" in text or "preemptible" in text:
            c["use_spot_instances"] = True
        if "reserved" in text or "reservation" in text:
            c["use_reserved_instances"] = True
        if "auto shutdown" in text or "stop at night" in text:
            c["auto_shutdown"] = True
        if "serverless" in text or "consumption" in text:
            c["prefer_serverless"] = True
        return c

    def _determine_validation_rules(
        self,
        resource_type: str,
        context: dict[str, Any],
        attributes: dict[str, object],
        cost_constraints: dict[str, Any],
        compliance: list[str],
    ) -> list[str]:
        rules: list[str] = []
        rules.extend(self.validation_rule_sets["naming"])
        if context.get("environment") == "production":
            rules.extend(self.validation_rule_sets["security"])
            rules.extend(self.validation_rule_sets["availability"])
            rules.extend(self.validation_rule_sets["performance"])
        if compliance:
            rules.extend(self.validation_rule_sets["compliance"])
        if cost_constraints:
            rules.extend(self.validation_rule_sets["cost"])
        if attributes.get("high_availability"):
            rules.extend(
                [
                    "multi_zone_deployment",
                    "load_balancer_configuration",
                    "health_probe_configuration",
                    "auto_failover",
                ]
            )
        if resource_type == "aks_cluster":
            rules.extend(
                [
                    "pod_security_policies",
                    "network_policies",
                    "ingress_configuration",
                    "cluster_autoscaler",
                    "node_pool_configuration",
                ]
            )
        elif resource_type == "database":
            rules.extend(
                [
                    "backup_retention",
                    "point_in_time_restore",
                    "geo_replication",
                    "connection_pooling",
                    "query_optimization",
                ]
            )
        elif resource_type == "webapp":
            rules.extend(
                [
                    "ssl_configuration",
                    "custom_domain",
                    "scaling_rules",
                    "deployment_slots",
                    "app_insights_integration",
                ]
            )
        return list(dict.fromkeys(rules))

    def _determine_deployment_strategy(
        self,
        intent: DeploymentIntent,
        context: dict[str, Any],
        attributes: dict[str, object],
    ) -> str:
        env = context.get("environment", "development")
        if env == "production":
            if intent == DeploymentIntent.UPDATE:
                return "blue_green"
            if intent == DeploymentIntent.CREATE and attributes.get(
                "high_availability"
            ):
                return "canary"
            return "rolling"
        if env in ["staging", "uat"]:
            return "rolling"
        return "direct"

    def _match_first(self, text: str, pattern_dict: dict[str, list[str]]) -> str | None:
        for k, patterns in pattern_dict.items():
            for p in patterns:
                if re.search(p, text):
                    return k
        return None

    def _calculate_confidence(
        self,
        text: str,
        intent: DeploymentIntent,
        resource_type: str,
        context: dict[str, Any],
    ) -> float:
        c = 0.5
        if intent != DeploymentIntent.CREATE:
            c += 0.1
        if resource_type != "generic":
            c += 0.2
        if context.get("resource_group") and context.get("subscription_id"):
            c += 0.15
        if re.search(
            r"\b(please|must|need to|have to|required|urgent)\b", text, re.IGNORECASE
        ):
            c += 0.1
        if len(text.split()) > 15:
            c += 0.05
        return min(c, 1.0)
