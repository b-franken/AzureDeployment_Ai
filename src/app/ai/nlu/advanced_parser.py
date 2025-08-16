from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class DeploymentPattern(Enum):
    MICROSERVICES = "microservices"
    MONOLITHIC = "monolithic"
    SERVERLESS = "serverless"
    HYBRID = "hybrid"
    EVENT_DRIVEN = "event_driven"
    BATCH_PROCESSING = "batch_processing"
    REAL_TIME = "real_time"
    DATA_PIPELINE = "data_pipeline"
    ML_PLATFORM = "ml_platform"
    IOT_PLATFORM = "iot_platform"


class SecurityRequirement(Enum):
    ZERO_TRUST = "zero_trust"
    DEFENSE_IN_DEPTH = "defense_in_depth"
    LEAST_PRIVILEGE = "least_privilege"
    ENCRYPTION_EVERYWHERE = "encryption_everywhere"
    NETWORK_ISOLATION = "network_isolation"
    IDENTITY_BASED = "identity_based"
    COMPLIANCE_DRIVEN = "compliance_driven"


@dataclass
class AdvancedDeploymentContext:
    pattern: DeploymentPattern
    security_requirements: list[SecurityRequirement]
    performance_requirements: dict[str, Any]
    availability_requirements: dict[str, Any]
    compliance_frameworks: list[str]
    data_residency: list[str]
    network_topology: dict[str, Any]
    integration_points: list[dict[str, Any]]
    monitoring_strategy: dict[str, Any]
    backup_strategy: dict[str, Any]
    disaster_recovery: dict[str, Any]
    cost_optimization: dict[str, Any]
    deployment_windows: list[tuple[datetime, datetime]]
    rollback_strategy: str
    approval_workflow: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


class AdvancedNLUEngine:
    def __init__(self) -> None:
        self.pattern_recognizers = self._initialize_pattern_recognizers()
        self.context_extractors = self._initialize_context_extractors()
        self.requirement_parsers = self._initialize_requirement_parsers()
        self.integration_detectors = self._initialize_integration_detectors()

    def _initialize_pattern_recognizers(self) -> dict[str, list[str]]:
        return {
            "microservices": [
                r"\b(microservice|micro-service|container|docker|kubernetes|service mesh)\b",
                r"\b(api gateway|service discovery|circuit breaker|saga pattern)\b",
            ],
            "serverless": [
                r"\b(serverless|function as a service|faas|lambda|azure functions)\b",
                r"\b(event driven|pay per use|consumption plan)\b",
            ],
            "ml_platform": [
                r"\b(machine learning|ml platform|mlops|model training|inference)\b",
                r"\b(data science|jupyter|databricks|azure ml|sagemaker)\b",
            ],
            "iot_platform": [
                r"\b(iot|internet of things|device management|telemetry|edge computing)\b",
                r"\b(iot hub|event hub|time series|stream analytics)\b",
            ],
            "data_pipeline": [
                r"\b(etl|elt|data pipeline|data factory|data flow|batch processing)\b",
                r"\b(data lake|data warehouse|synapse|databricks|spark)\b",
            ],
        }

    def _initialize_context_extractors(self) -> dict[str, Any]:
        return {
            "availability": {
                "patterns": [
                    r"(\d+\.?\d*)\s*%?\s*(?:availability|uptime|sla)",
                    r"(high|medium|low)\s+availability",
                    r"(24[/x]7|business hours|working hours)",
                ],
                "extractors": self._extract_availability_requirements,
            },
            "performance": {
                "patterns": [
                    r"(\d+)\s*(ms|milliseconds?|seconds?|s)\s*(?:latency|response time)",
                    r"(\d+)\s*(rps|tps|qps|requests?/s|transactions?/s)",
                    r"(high|medium|low)\s+(?:performance|throughput)",
                ],
                "extractors": self._extract_performance_requirements,
            },
            "scale": {
                "patterns": [
                    r"(\d+[kmb]?)\s*(?:users?|requests?|transactions?)",
                    r"(auto|manual|scheduled)\s*scal(?:e|ing)",
                    r"scale\s+(?:to|up to|down to)\s+(\d+)",
                ],
                "extractors": self._extract_scale_requirements,
            },
            "security": {
                "patterns": [
                    r"\b(zero trust|least privilege|defense in depth)\b",
                    r"\b(encryption|tls|ssl|https|vpn|private endpoint)\b",
                    r"\b(waf|firewall|ddos protection|threat protection)\b",
                ],
                "extractors": self._extract_security_requirements,
            },
        }

    def _initialize_requirement_parsers(self) -> dict[str, Any]:
        return {
            "networking": self._parse_networking_requirements,
            "storage": self._parse_storage_requirements,
            "compute": self._parse_compute_requirements,
            "integration": self._parse_integration_requirements,
            "monitoring": self._parse_monitoring_requirements,
        }

    def _initialize_integration_detectors(self) -> dict[str, list[str]]:
        return {
            "salesforce": [r"\b(salesforce|sfdc|crm)\b"],
            "sap": [r"\b(sap|erp|s/4hana|hana)\b"],
            "office365": [r"\b(office 365|o365|teams|sharepoint|exchange online)\b"],
            "dynamics": [r"\b(dynamics 365|dynamics crm|dynamics erp)\b"],
            "servicenow": [r"\b(servicenow|snow|itsm|itom)\b"],
            "github": [r"\b(github|git|source control|version control|ci/cd)\b"],
            "jenkins": [r"\b(jenkins|ci/cd|continuous integration|build pipeline)\b"],
            "terraform": [r"\b(terraform|infrastructure as code|iac)\b"],
            "ansible": [r"\b(ansible|configuration management|playbook)\b"],
            "datadog": [r"\b(datadog|apm|application monitoring)\b"],
            "splunk": [r"\b(splunk|log analytics|siem)\b"],
            "elastic": [r"\b(elastic|elasticsearch|elk stack|kibana)\b"],
        }

    def parse_advanced_context(self, text: str) -> AdvancedDeploymentContext:
        text_lower = text.lower()

        pattern = self._detect_deployment_pattern(text_lower)
        security_reqs = self._extract_security_requirements(text_lower)
        performance_reqs = self._extract_performance_requirements(text_lower)
        availability_reqs = self._extract_availability_requirements(text_lower)
        compliance = self._detect_compliance_frameworks(text_lower)
        data_residency = self._extract_data_residency(text_lower)
        network_topology = self._extract_network_topology(text_lower)
        integrations = self._detect_integrations(text_lower)
        monitoring = self._extract_monitoring_strategy(text_lower)
        backup = self._extract_backup_strategy(text_lower)
        dr = self._extract_disaster_recovery(text_lower)
        cost_opt = self._extract_cost_optimization(text_lower)
        windows = self._extract_deployment_windows(text_lower)
        rollback = self._determine_rollback_strategy(text_lower)
        approval = self._extract_approval_workflow(text_lower)

        return AdvancedDeploymentContext(
            pattern=pattern,
            security_requirements=security_reqs,
            performance_requirements=performance_reqs,
            availability_requirements=availability_reqs,
            compliance_frameworks=compliance,
            data_residency=data_residency,
            network_topology=network_topology,
            integration_points=integrations,
            monitoring_strategy=monitoring,
            backup_strategy=backup,
            disaster_recovery=dr,
            cost_optimization=cost_opt,
            deployment_windows=windows,
            rollback_strategy=rollback,
            approval_workflow=approval,
            metadata={"original_text": text, "parsed_at": datetime.utcnow().isoformat()},
        )

    def _detect_deployment_pattern(self, text: str) -> DeploymentPattern:
        scores: dict[str, int] = {}

        for pattern_name, patterns in self.pattern_recognizers.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    score += 2
            if score > 0:
                scores[pattern_name] = score

        if not scores:
            return DeploymentPattern.MONOLITHIC

        best_match = max(scores, key=scores.__getitem__)

        pattern_map = {
            "microservices": DeploymentPattern.MICROSERVICES,
            "serverless": DeploymentPattern.SERVERLESS,
            "ml_platform": DeploymentPattern.ML_PLATFORM,
            "iot_platform": DeploymentPattern.IOT_PLATFORM,
            "data_pipeline": DeploymentPattern.DATA_PIPELINE,
        }

        return pattern_map.get(best_match, DeploymentPattern.HYBRID)

    def _extract_security_requirements(self, text: str) -> list[SecurityRequirement]:
        requirements: list[SecurityRequirement] = []

        if re.search(r"\b(zero trust|never trust)\b", text, re.IGNORECASE):
            requirements.append(SecurityRequirement.ZERO_TRUST)

        if re.search(r"\b(defense in depth|layered security)\b", text, re.IGNORECASE):
            requirements.append(SecurityRequirement.DEFENSE_IN_DEPTH)

        if re.search(r"\b(least privilege|minimal access)\b", text, re.IGNORECASE):
            requirements.append(SecurityRequirement.LEAST_PRIVILEGE)

        if re.search(
            r"\b(encrypt everything|encryption everywhere|always encrypted)\b",
            text,
            re.IGNORECASE,
        ):
            requirements.append(SecurityRequirement.ENCRYPTION_EVERYWHERE)

        if re.search(
            r"\b(network isolation|isolated network|private network)\b",
            text,
            re.IGNORECASE,
        ):
            requirements.append(SecurityRequirement.NETWORK_ISOLATION)

        if re.search(
            r"\b(identity based|managed identity|service principal)\b",
            text,
            re.IGNORECASE,
        ):
            requirements.append(SecurityRequirement.IDENTITY_BASED)

        if any(fw in text for fw in ["gdpr", "hipaa", "pci", "sox", "iso27001"]):
            requirements.append(SecurityRequirement.COMPLIANCE_DRIVEN)

        return requirements or [SecurityRequirement.DEFENSE_IN_DEPTH]

    def _extract_performance_requirements(self, text: str) -> dict[str, Any]:
        reqs: dict[str, Any] = {}

        latency_match = re.search(
            r"(\d+)\s*(ms|milliseconds?|seconds?|s)\s*(?:latency|response time)",
            text,
            re.IGNORECASE,
        )
        if latency_match:
            value = int(latency_match.group(1))
            unit = latency_match.group(2).lower()
            if "s" in unit and "ms" not in unit:
                value *= 1000
            reqs["max_latency_ms"] = value

        throughput_match = re.search(
            r"(\d+)\s*(rps|tps|qps|requests?/s|transactions?/s)", text, re.IGNORECASE
        )
        if throughput_match:
            reqs["min_throughput_rps"] = int(throughput_match.group(1))

        if "high performance" in text or "low latency" in text:
            reqs["performance_tier"] = "premium"
        elif "standard performance" in text:
            reqs["performance_tier"] = "standard"
        else:
            reqs["performance_tier"] = "standard"

        return reqs

    def _extract_availability_requirements(self, text: str) -> dict[str, Any]:
        reqs: dict[str, Any] = {}

        sla_match = re.search(
            r"(\d+\.?\d*)\s*%?\s*(?:availability|uptime|sla)", text, re.IGNORECASE
        )
        if sla_match:
            reqs["sla_percentage"] = float(sla_match.group(1))

        if "24/7" in text or "24x7" in text:
            reqs["availability_window"] = "24x7"
        elif "business hours" in text:
            reqs["availability_window"] = "business_hours"
        else:
            reqs["availability_window"] = "24x7"

        if "high availability" in text or "ha" in text:
            reqs["high_availability"] = True
            reqs["min_replicas"] = 2

        if "disaster recovery" in text or "dr" in text:
            reqs["disaster_recovery"] = True
            reqs["rto_hours"] = 4
            reqs["rpo_hours"] = 1

        return reqs

    def _extract_scale_requirements(self, text: str) -> dict[str, Any]:
        reqs: dict[str, Any] = {}

        users_match = re.search(r"(\d+[kmb]?)\s*(?:users?|concurrent users?)", text, re.IGNORECASE)
        if users_match:
            value_str = users_match.group(1).lower()
            multiplier = {"k": 1000, "m": 1000000, "b": 1000000000}
            if value_str[-1] in multiplier:
                value = int(value_str[:-1]) * multiplier[value_str[-1]]
            else:
                value = int(value_str)
            reqs["max_concurrent_users"] = value

        if "auto scale" in text or "autoscale" in text:
            reqs["autoscale_enabled"] = True
            reqs["autoscale_min"] = 2
            reqs["autoscale_max"] = 10

        return reqs

    def _detect_compliance_frameworks(self, text: str) -> list[str]:
        frameworks: list[str] = []

        compliance_map = {
            "gdpr": ["gdpr", "general data protection"],
            "hipaa": ["hipaa", "health insurance portability"],
            "pci_dss": ["pci", "payment card industry"],
            "sox": ["sox", "sarbanes"],
            "iso27001": ["iso 27001", "iso27001"],
            "fedramp": ["fedramp", "federal risk"],
        }

        for framework, patterns in compliance_map.items():
            for pattern in patterns:
                if pattern in text:
                    frameworks.append(framework)
                    break

        return frameworks

    def _extract_data_residency(self, text: str) -> list[str]:
        regions: list[str] = []

        region_patterns = {
            "eu": ["eu", "europe", "gdpr region"],
            "us": ["us", "united states", "america"],
            "uk": ["uk", "united kingdom", "britain"],
            "canada": ["canada", "canadian"],
            "australia": ["australia", "australian"],
            "asia": ["asia", "apac", "asia pacific"],
        }

        for region, patterns in region_patterns.items():
            for pattern in patterns:
                if pattern in text:
                    regions.append(region)
                    break

        return regions or ["global"]

    def _extract_network_topology(self, text: str) -> dict[str, Any]:
        topology: dict[str, Any] = {}

        if "hub and spoke" in text or "hub-spoke" in text:
            topology["type"] = "hub_spoke"
        elif "mesh" in text:
            topology["type"] = "mesh"
        elif "point to point" in text:
            topology["type"] = "point_to_point"
        else:
            topology["type"] = "simple"

        if "vpn" in text or "site to site" in text:
            topology["vpn_required"] = True

        if "express route" in text or "expressroute" in text:
            topology["expressroute_required"] = True

        if "private endpoint" in text or "private link" in text:
            topology["private_endpoints"] = True

        if "vnet peering" in text:
            topology["vnet_peering"] = True

        return topology

    def _detect_integrations(self, text: str) -> list[dict[str, Any]]:
        integrations: list[dict[str, Any]] = []

        for system, patterns in self.integration_detectors.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    integrations.append(
                        {
                            "system": system,
                            "type": self._determine_integration_type(system),
                            "method": self._determine_integration_method(system, text),
                        }
                    )
                    break

        return integrations

    def _determine_integration_type(self, system: str) -> str:
        type_map = {
            "salesforce": "crm",
            "sap": "erp",
            "office365": "productivity",
            "dynamics": "business_apps",
            "servicenow": "itsm",
            "github": "source_control",
            "jenkins": "ci_cd",
            "terraform": "iac",
            "ansible": "configuration",
            "datadog": "monitoring",
            "splunk": "logging",
            "elastic": "search",
        }
        return type_map.get(system, "external")

    def _determine_integration_method(self, system: str, text: str) -> str:
        if "api" in text:
            return "api"
        elif "webhook" in text:
            return "webhook"
        elif "event" in text:
            return "event_driven"
        elif "batch" in text:
            return "batch"
        else:
            return "api"

    def _extract_monitoring_strategy(self, text: str) -> dict[str, Any]:
        strategy: dict[str, Any] = {}

        if "application insights" in text or "app insights" in text:
            strategy["apm"] = "application_insights"
        elif "datadog" in text:
            strategy["apm"] = "datadog"
        elif "new relic" in text:
            strategy["apm"] = "new_relic"

        if "log analytics" in text:
            strategy["logging"] = "log_analytics"
        elif "splunk" in text:
            strategy["logging"] = "splunk"
        elif "elastic" in text or "elk" in text:
            strategy["logging"] = "elk"

        if "prometheus" in text:
            strategy["metrics"] = "prometheus"
        elif "grafana" in text:
            strategy["visualization"] = "grafana"

        if "alert" in text or "notification" in text:
            strategy["alerting"] = True
            if "pagerduty" in text:
                strategy["alerting_platform"] = "pagerduty"
            elif "opsgenie" in text:
                strategy["alerting_platform"] = "opsgenie"

        if not strategy:
            return {
                "apm": "application_insights",
                "logging": "log_analytics",
                "alerting": True,
            }
        return strategy

    def _extract_backup_strategy(self, text: str) -> dict[str, Any]:
        strategy: dict[str, Any] = {}

        if "daily backup" in text:
            strategy["frequency"] = "daily"
        elif "hourly backup" in text:
            strategy["frequency"] = "hourly"
        elif "weekly backup" in text:
            strategy["frequency"] = "weekly"
        else:
            strategy["frequency"] = "daily"

        retention_match = re.search(
            r"(\d+)\s*(?:days?|weeks?|months?)\s*retention", text, re.IGNORECASE
        )
        if retention_match:
            strategy["retention_days"] = int(retention_match.group(1))
        else:
            strategy["retention_days"] = 30

        if "geo redundant" in text or "grs" in text:
            strategy["geo_redundant"] = True

        if "point in time" in text or "pitr" in text:
            strategy["point_in_time_restore"] = True

        return strategy

    def _extract_disaster_recovery(self, text: str) -> dict[str, Any]:
        dr: dict[str, Any] = {}

        rto_match = re.search(r"rto\s*(?:of)?\s*(\d+)\s*(?:hours?|hrs?)", text, re.IGNORECASE)
        if rto_match:
            dr["rto_hours"] = int(rto_match.group(1))

        rpo_match = re.search(
            r"rpo\s*(?:of)?\s*(\d+)\s*(?:hours?|hrs?|minutes?|mins?)",
            text,
            re.IGNORECASE,
        )
        if rpo_match:
            dr["rpo_hours"] = int(rpo_match.group(1))

        if "active active" in text or "active-active" in text:
            dr["strategy"] = "active_active"
        elif "active passive" in text or "active-passive" in text:
            dr["strategy"] = "active_passive"
        elif "pilot light" in text:
            dr["strategy"] = "pilot_light"
        elif "warm standby" in text:
            dr["strategy"] = "warm_standby"

        if "failover" in text:
            dr["automatic_failover"] = "automatic" in text

        return dr

    def _extract_cost_optimization(self, text: str) -> dict[str, Any]:
        cost_opt: dict[str, Any] = {}

        if "reserved instance" in text or "reservation" in text:
            cost_opt["use_reserved_instances"] = True

        if "spot instance" in text or "spot vm" in text:
            cost_opt["use_spot_instances"] = True

        if "auto shutdown" in text or "scheduled shutdown" in text:
            cost_opt["auto_shutdown"] = True

        if "dev test" in text or "dev/test" in text:
            cost_opt["dev_test_pricing"] = True

        budget_match = re.search(
            r"\$?(\d+[kmb]?)\s*(?:budget|cost limit|spend limit)",
            text,
            re.IGNORECASE,
        )
        if budget_match:
            value_str = budget_match.group(1).lower()
            multiplier = {"k": 1000, "m": 1000000, "b": 1000000000}
            if value_str[-1] in multiplier:
                value = int(value_str[:-1]) * multiplier[value_str[-1]]
            else:
                value = int(value_str)
            cost_opt["monthly_budget"] = value

        return cost_opt

    def _extract_deployment_windows(self, text: str) -> list[tuple[datetime, datetime]]:
        windows: list[tuple[datetime, datetime]] = []

        if "maintenance window" in text:
            if "weekend" in text:
                start = datetime.utcnow().replace(hour=22, minute=0, second=0, microsecond=0)
                start += timedelta(days=(5 - start.weekday()) % 7)
                end = start + timedelta(hours=6)
                windows.append((start, end))
            elif "overnight" in text or "night" in text:
                start = datetime.utcnow().replace(hour=22, minute=0, second=0, microsecond=0)
                end = start + timedelta(hours=6)
                windows.append((start, end))

        return windows

    def _determine_rollback_strategy(self, text: str) -> str:
        if "blue green" in text or "blue-green" in text:
            return "blue_green"
        elif "canary" in text:
            return "canary"
        elif "rolling" in text:
            return "rolling"
        elif "immediate rollback" in text:
            return "immediate"
        else:
            return "manual"

    def _extract_approval_workflow(self, text: str) -> dict[str, Any]:
        workflow: dict[str, Any] = {}

        if "approval required" in text or "requires approval" in text:
            workflow["required"] = True

            if "manager approval" in text:
                workflow["approvers"] = ["manager"]
            elif "security approval" in text:
                workflow["approvers"] = ["security_team"]
            elif "change board" in text or "cab" in text:
                workflow["approvers"] = ["change_advisory_board"]
            else:
                workflow["approvers"] = ["admin"]

            if "emergency" in text:
                workflow["emergency_bypass"] = True
        else:
            workflow["required"] = False

        return workflow

    def _parse_networking_requirements(self, text: str) -> dict[str, Any]:
        return self._extract_network_topology(text)

    def _parse_storage_requirements(self, text: str) -> dict[str, Any]:
        storage: dict[str, Any] = {}

        if "blob storage" in text:
            storage["blob_storage"] = True
        if "file share" in text:
            storage["file_share"] = True
        if "data lake" in text:
            storage["data_lake"] = True
        if "archive" in text:
            storage["archive_tier"] = True

        size_match = re.search(r"(\d+)\s*(gb|tb|pb)", text, re.IGNORECASE)
        if size_match:
            size = int(size_match.group(1))
            unit = size_match.group(2).lower()
            if unit == "tb":
                size *= 1024
            elif unit == "pb":
                size *= 1024 * 1024
            storage["size_gb"] = size

        return storage

    def _parse_compute_requirements(self, text: str) -> dict[str, Any]:
        compute: dict[str, Any] = {}

        if "gpu" in text:
            compute["gpu_enabled"] = True

        cpu_match = re.search(r"(\d+)\s*(?:vcpus?|cores?|cpus?)", text, re.IGNORECASE)
        if cpu_match:
            compute["vcpus"] = int(cpu_match.group(1))

        ram_match = re.search(r"(\d+)\s*(?:gb|gib)\s*(?:ram|memory)", text, re.IGNORECASE)
        if ram_match:
            compute["memory_gb"] = int(ram_match.group(1))

        return compute

    def _parse_integration_requirements(self, text: str) -> list[dict[str, Any]]:
        return self._detect_integrations(text)

    def _parse_monitoring_requirements(self, text: str) -> dict[str, Any]:
        return self._extract_monitoring_strategy(text)
