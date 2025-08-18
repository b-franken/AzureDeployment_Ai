from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from app.tools.finops.cost_ingestion import CostIngestionService
from app.tools.finops.resource_discovery import ResourceDiscoveryService


class OptimizationStrategy(Enum):
    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"
    CONSERVATIVE = "conservative"


@dataclass
class OptimizationRecommendation:
    id: str
    resource_id: str
    resource_type: str
    recommendation_type: str
    description: str
    estimated_monthly_savings: float
    estimated_savings_percentage: float
    implementation_effort: str
    risk_level: str
    actions: list[dict[str, Any]]
    validation_steps: list[str]
    rollback_plan: str


class OptimizationService:
    def __init__(self):
        self.discovery = ResourceDiscoveryService()
        self.cost_ingestion = CostIngestionService()

    async def analyze_optimization_opportunities(
        self,
        subscription_id: str,
        strategy: OptimizationStrategy = OptimizationStrategy.BALANCED,
        min_savings_threshold: float = 50.0,
    ) -> list[OptimizationRecommendation]:
        resources = await self.discovery.discover_resources(subscription_id)

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)

        resource_ids = [r["id"] for r in resources]
        costs = await self.cost_ingestion.get_resource_costs(
            f"/subscriptions/{subscription_id}",
            resource_ids,
            start_date,
            end_date,
        )

        recommendations: list[OptimizationRecommendation] = []

        tasks = [
            self._analyze_vm_optimization(subscription_id, r, costs.get(r["id"], {}), strategy)
            for r in resources
            if r["type"].lower().startswith("microsoft.compute/virtualmachines")
        ]
        tasks.extend(
            [
                self._analyze_storage_optimization(
                    subscription_id, r, costs.get(r["id"], {}), strategy
                )
                for r in resources
                if r["type"].lower().startswith("microsoft.storage/storageaccounts")
            ]
        )
        tasks.extend(
            [
                self._analyze_aks_optimization(subscription_id, r, costs.get(r["id"], {}), strategy)
                for r in resources
                if r["type"].lower().startswith("microsoft.containerservice/managedclusters")
            ]
        )
        tasks.extend(
            [
                self._analyze_database_optimization(
                    subscription_id, r, costs.get(r["id"], {}), strategy
                )
                for r in resources
                if "sql" in r["type"].lower() or "database" in r["type"].lower()
            ]
        )

        all_recommendations = await asyncio.gather(*tasks, return_exceptions=True)

        for rec_list in all_recommendations:
            if isinstance(rec_list, list):
                for rec in rec_list:
                    if rec.estimated_monthly_savings >= min_savings_threshold:
                        recommendations.append(rec)

        return sorted(recommendations, key=lambda x: x.estimated_monthly_savings, reverse=True)

    async def _analyze_vm_optimization(
        self,
        subscription_id: str,
        resource: dict[str, Any],
        cost_info: dict[str, Any],
        strategy: OptimizationStrategy,
    ) -> list[OptimizationRecommendation]:
        recommendations: list[OptimizationRecommendation] = []
        resource_id = resource["id"]
        monthly_cost = cost_info.get("cost_usd", 0.0)

        metrics = await self.discovery.get_resource_metrics(
            subscription_id,
            resource_id,
            ["Percentage CPU", "Available Memory Bytes", "Disk Read Bytes", "Disk Write Bytes"],
            "PT7D",
        )

        cpu_metrics = metrics.get("Percentage CPU", [])
        if cpu_metrics:
            # Treat missing values as None and include zeros
            valid = [m["average"] for m in cpu_metrics if m.get("average") is not None]
            if valid:
                avg_cpu = sum(valid) / len(valid)

                # Right-sizing recommendation for underutilized VMs
                if 5 < avg_cpu < 20:
                    recommendations.append(
                        OptimizationRecommendation(
                            id=f"opt-vm-{resource['name']}-rightsize",
                            resource_id=resource_id,
                            resource_type="Virtual Machine",
                            recommendation_type="right_sizing",
                            description=(
                                f"VM {resource['name']} has average CPU usage of {avg_cpu:.1f}%. "
                                "Consider downsizing."
                            ),
                            estimated_monthly_savings=monthly_cost * 0.3,
                            estimated_savings_percentage=30.0,
                            implementation_effort="medium",
                            risk_level="low"
                            if strategy == OptimizationStrategy.CONSERVATIVE
                            else "medium",
                            actions=[
                                {"action": "analyze_workload_patterns", "duration": "1 week"},
                                {"action": "identify_smaller_sku", "target": "reduce by 1-2 sizes"},
                                {
                                    "action": "schedule_maintenance_window",
                                    "downtime": "5-10 minutes",
                                },
                                {"action": "resize_vm", "automation": "Azure CLI or Portal"},
                                {"action": "monitor_performance", "duration": "1 week post-change"},
                            ],
                            validation_steps=[
                                "Verify application performance metrics remain within SLA",
                                "Check CPU usage stays below 70% after resize",
                                "Confirm memory usage is adequate",
                                "Test application response times",
                            ],
                            rollback_plan="Resize back to original SKU if performance degrades",
                        )
                    )

                # Auto-shutdown recommendation for very low usage VMs
                if avg_cpu < 5 and strategy != OptimizationStrategy.CONSERVATIVE:
                    recommendations.append(
                        OptimizationRecommendation(
                            id=f"opt-vm-{resource['name']}-shutdown",
                            resource_id=resource_id,
                            resource_type="Virtual Machine",
                            recommendation_type="auto_shutdown",
                            description=(
                                f"VM {resource['name']} has very low usage ({avg_cpu:.1f}%). "
                                "Consider auto-shutdown or deletion."
                            ),
                            estimated_monthly_savings=monthly_cost * 0.8,
                            estimated_savings_percentage=80.0,
                            implementation_effort="low",
                            risk_level="medium",
                            actions=[
                                {"action": "verify_vm_necessity", "owner": "application_team"},
                                {
                                    "action": "implement_auto_shutdown",
                                    "schedule": "nights and weekends",
                                },
                                {
                                    "action": "setup_auto_start",
                                    "trigger": "on demand or schedule",
                                },
                                {"action": "configure_alerts", "threshold": "before shutdown"},
                            ],
                            validation_steps=[
                                "Confirm with application owners about usage patterns",
                                "Document shutdown and startup procedures",
                                "Test auto-shutdown in non-production first",
                                "Verify no batch jobs run during shutdown periods",
                            ],
                            rollback_plan="Disable auto-shutdown policy and keep VM running",
                        )
                    )

        # Check for reservation opportunities
        reservation_rec = await self._check_reservation_opportunity(
            subscription_id, resource, monthly_cost, strategy
        )
        if reservation_rec:
            recommendations.append(reservation_rec)

        # Check for spot instance opportunities
        spot_rec = await self._check_spot_opportunity(resource, monthly_cost, strategy)
        if spot_rec:
            recommendations.append(spot_rec)

        return recommendations

    async def _analyze_storage_optimization(
        self,
        subscription_id: str,
        resource: dict[str, Any],
        cost_info: dict[str, Any],
        strategy: OptimizationStrategy,
    ) -> list[OptimizationRecommendation]:
        recommendations: list[OptimizationRecommendation] = []
        resource_id = resource["id"]
        monthly_cost = cost_info.get("cost_usd", 0.0)

        sku = resource.get("sku", {})

        # Redundancy optimization
        if (
            sku.get("name", "").startswith("Standard_GRS")
            and strategy != OptimizationStrategy.CONSERVATIVE
        ):
            recommendations.append(
                OptimizationRecommendation(
                    id=f"opt-storage-{resource['name']}-redundancy",
                    resource_id=resource_id,
                    resource_type="Storage Account",
                    recommendation_type="redundancy_optimization",
                    description=(
                        f"Storage account {resource['name']} uses GRS. Consider LRS for "
                        "non-critical data."
                    ),
                    estimated_monthly_savings=monthly_cost * 0.5,
                    estimated_savings_percentage=50.0,
                    implementation_effort="low",
                    risk_level=(
                        "medium" if strategy == OptimizationStrategy.AGGRESSIVE else "high"
                    ),
                    actions=[
                        {
                            "action": "assess_data_criticality",
                            "review": "business requirements",
                        },
                        {
                            "action": "check_compliance_requirements",
                            "verify": "data residency rules",
                        },
                        {
                            "action": "change_replication",
                            "target": "Standard_LRS or Standard_ZRS",
                        },
                        {
                            "action": "update_disaster_recovery_plan",
                            "document": "new RTO/RPO",
                        },
                    ],
                    validation_steps=[
                        "Verify backup strategy covers critical data",
                        "Confirm compliance with data durability requirements",
                        "Test restore procedures with new redundancy level",
                        "Update documentation about redundancy changes",
                    ],
                    rollback_plan=("Change replication back to GRS through portal or CLI"),
                )
            )

        # Lifecycle management recommendation
        lifecycle_rec = await self._analyze_storage_lifecycle(resource, monthly_cost)
        if lifecycle_rec:
            recommendations.append(lifecycle_rec)

        return recommendations

    async def _analyze_aks_optimization(
        self,
        subscription_id: str,
        resource: dict[str, Any],
        cost_info: dict[str, Any],
        strategy: OptimizationStrategy,
    ) -> list[OptimizationRecommendation]:
        recommendations: list[OptimizationRecommendation] = []
        resource_id = resource["id"]
        monthly_cost = cost_info.get("cost_usd", 0.0)

        properties = resource.get("properties", {})
        agent_pools = properties.get("agentPoolProfiles", [])

        for pool in agent_pools:
            if not pool.get("enableAutoScaling", False):
                pool_name = pool.get("name", "default")
                rec_id = f"opt-aks-{resource['name']}-autoscale-{pool_name}"
                desc = f"Enable autoscaling for node pool {pool_name}"
                recommendations.append(
                    OptimizationRecommendation(
                        id=rec_id,
                        resource_id=resource_id,
                        resource_type="AKS Cluster",
                        recommendation_type="enable_autoscaling",
                        description=desc,
                        estimated_monthly_savings=monthly_cost * 0.25,
                        estimated_savings_percentage=25.0,
                        implementation_effort="medium",
                        risk_level="low",
                        actions=[
                            {
                                "action": "analyze_workload_patterns",
                                "metrics": "cpu, memory, pod count",
                            },
                            {
                                "action": "determine_min_max_nodes",
                                "based_on": "historical usage",
                            },
                            {
                                "action": "enable_cluster_autoscaler",
                                "method": "az aks update",
                            },
                            {
                                "action": "configure_scale_down_delay",
                                "value": "10 minutes",
                            },
                            {
                                "action": "set_scale_down_utilization",
                                "threshold": "0.5",
                            },
                        ],
                        validation_steps=[
                            "Monitor node scaling events for 1 week",
                            "Verify pod scheduling latency remains acceptable",
                            "Check for any pod evictions during scale-down",
                            "Review autoscaler metrics and adjust thresholds",
                        ],
                        rollback_plan="Disable autoscaling and set fixed node count",
                    )
                )

        if strategy == OptimizationStrategy.AGGRESSIVE:
            spot_pool_rec = self._suggest_spot_node_pool(resource, monthly_cost)
            if spot_pool_rec:
                recommendations.append(spot_pool_rec)

        return recommendations

    async def _analyze_database_optimization(
        self,
        subscription_id: str,
        resource: dict[str, Any],
        cost_info: dict[str, Any],
        strategy: OptimizationStrategy,
    ) -> list[OptimizationRecommendation]:
        recommendations: list[OptimizationRecommendation] = []
        resource_id = resource["id"]
        monthly_cost = cost_info.get("cost_usd", 0.0)

        if "sql" in resource["type"].lower():
            metrics = await self.discovery.get_resource_metrics(
                subscription_id,
                resource_id,
                ["cpu_percent", "dtu_consumption_percent", "storage_percent"],
                "PT7D",
            )

            cpu_metrics = metrics.get("cpu_percent", [])
            if cpu_metrics:
                valid = [m["average"] for m in cpu_metrics if m.get("average") is not None]
                if valid:
                    avg_cpu = sum(valid) / len(valid)

                    if avg_cpu < 20:
                        recommendations.append(
                            OptimizationRecommendation(
                                id=f"opt-sql-{resource['name']}-elastic",
                                resource_id=resource_id,
                                resource_type="SQL Database",
                                recommendation_type="elastic_pool",
                                description=(
                                    "SQL Database has low usage. "
                                    "Consider elastic pool for multiple databases."
                                ),
                                estimated_monthly_savings=monthly_cost * 0.4,
                                estimated_savings_percentage=40.0,
                                implementation_effort="high",
                                risk_level="medium",
                                actions=[
                                    {
                                        "action": "identify_databases_for_pool",
                                        "criteria": "similar usage patterns",
                                    },
                                    {
                                        "action": "calculate_pool_edtu",
                                        "method": "sum of peak DTUs",
                                    },
                                    {
                                        "action": "create_elastic_pool",
                                        "sizing": "based on combined workload",
                                    },
                                    {
                                        "action": "migrate_databases",
                                        "method": "online migration",
                                    },
                                    {
                                        "action": "monitor_pool_utilization",
                                        "duration": "2 weeks",
                                    },
                                ],
                                validation_steps=[
                                    "Verify all databases meet elastic pool limitations",
                                    "Test application connectivity after migration",
                                    "Monitor DTU consumption across pool",
                                    "Validate query performance remains acceptable",
                                ],
                                rollback_plan="Move databases back to single database model",
                            )
                        )

        if strategy != OptimizationStrategy.CONSERVATIVE:
            serverless_rec = self._suggest_serverless_compute(resource, monthly_cost)
            if serverless_rec:
                recommendations.append(serverless_rec)

        return recommendations

    async def _check_reservation_opportunity(
        self,
        subscription_id: str,
        resource: dict[str, Any],
        monthly_cost: float,
        strategy: OptimizationStrategy,
    ) -> OptimizationRecommendation | None:
        if monthly_cost < 100 or strategy == OptimizationStrategy.CONSERVATIVE:
            return None

        scope = f"/subscriptions/{subscription_id}"
        recommendations = await self.cost_ingestion.get_reservation_recommendations(scope)

        for rec in recommendations:
            if resource["location"] == rec.get("location"):
                savings = rec.get("net_savings", 0)
                if savings > 0:
                    return OptimizationRecommendation(
                        id=f"opt-vm-{resource['name']}-reservation",
                        resource_id=resource["id"],
                        resource_type="Virtual Machine",
                        recommendation_type="reserved_instance",
                        description=(
                            f"Purchase {rec.get('recommended_quantity', 1)} year reservation "
                            "for consistent savings"
                        ),
                        estimated_monthly_savings=savings / 12,
                        estimated_savings_percentage=35.0,
                        implementation_effort="low",
                        risk_level="low",
                        actions=[
                            {"action": "review_usage_history", "period": "last 3 months"},
                            {"action": "confirm_long_term_need", "duration": "1-3 years"},
                            {"action": "calculate_break_even", "metric": "months to ROI"},
                            {
                                "action": "purchase_reservation",
                                "portal": "Azure Cost Management",
                            },
                            {
                                "action": "apply_reservation",
                                "scope": "shared or single subscription",
                            },
                        ],
                        validation_steps=[
                            "Verify VM will run continuously for reservation term",
                            "Confirm SKU family matches reservation",
                            "Check instance size flexibility settings",
                            "Monitor reservation utilization weekly",
                        ],
                        rollback_plan="Exchange or refund reservation within cancellation period",
                    )

        return None

    async def _check_spot_opportunity(
        self,
        resource: dict[str, Any],
        monthly_cost: float,
        strategy: OptimizationStrategy,
    ) -> OptimizationRecommendation | None:
        if strategy != OptimizationStrategy.AGGRESSIVE:
            return None

        tags = resource.get("tags", {})
        if tags.get("environment", "").lower() in ["prod", "production"]:
            return None

        return OptimizationRecommendation(
            id=f"opt-vm-{resource['name']}-spot",
            resource_id=resource["id"],
            resource_type="Virtual Machine",
            recommendation_type="spot_instance",
            description=f"Convert {resource['name']} to Spot VM for significant savings",
            estimated_monthly_savings=monthly_cost * 0.7,
            estimated_savings_percentage=70.0,
            implementation_effort="high",
            risk_level="high",
            actions=[
                {"action": "assess_interruption_tolerance", "requirement": "stateless workload"},
                {"action": "implement_graceful_shutdown", "handler": "deallocate notification"},
                {"action": "setup_restart_automation", "tool": "Azure Automation or Logic Apps"},
                {"action": "convert_to_spot", "max_price": "pay-as-you-go rate"},
                {"action": "monitor_eviction_rate", "alert": "if > 10% weekly"},
            ],
            validation_steps=[
                "Test application handles interruption gracefully",
                "Verify data persistence across restarts",
                "Monitor spot pricing trends in region",
                "Validate automation restarts VMs correctly",
            ],
            rollback_plan="Convert back to regular VM with guaranteed capacity",
        )

    async def _analyze_storage_lifecycle(
        self,
        resource: dict[str, Any],
        monthly_cost: float,
    ) -> OptimizationRecommendation | None:
        properties = resource.get("properties", {})
        if properties.get("isHnsEnabled", False):
            return OptimizationRecommendation(
                id=f"opt-storage-{resource['name']}-lifecycle",
                resource_id=resource["id"],
                resource_type="Storage Account",
                recommendation_type="lifecycle_management",
                description="Implement lifecycle policies to move cold data to cheaper tiers",
                estimated_monthly_savings=monthly_cost * 0.3,
                estimated_savings_percentage=30.0,
                implementation_effort="medium",
                risk_level="low",
                actions=[
                    {"action": "analyze_access_patterns", "tool": "Storage Analytics logs"},
                    {"action": "identify_cold_data", "criteria": "not accessed in 30 days"},
                    {"action": "create_lifecycle_policy", "rules": "move to cool after 30 days"},
                    {"action": "add_archive_rule", "condition": "not accessed in 90 days"},
                    {"action": "enable_policy", "scope": "selected containers"},
                ],
                validation_steps=[
                    "Review data access patterns for 1 month",
                    "Test retrieval time from cool or archive tiers",
                    "Verify critical data excluded from policies",
                    "Monitor tier distribution weekly",
                ],
                rollback_plan="Disable lifecycle policies and rehydrate archived data if needed",
            )
        return None

    def _suggest_spot_node_pool(
        self,
        resource: dict[str, Any],
        monthly_cost: float,
    ) -> OptimizationRecommendation | None:
        return OptimizationRecommendation(
            id=f"opt-aks-{resource['name']}-spot-pool",
            resource_id=resource["id"],
            resource_type="AKS Cluster",
            recommendation_type="spot_node_pool",
            description="Add spot node pool for non-critical workloads",
            estimated_monthly_savings=monthly_cost * 0.3,
            estimated_savings_percentage=30.0,
            implementation_effort="high",
            risk_level="medium",
            actions=[
                {"action": "identify_tolerant_workloads", "examples": "batch jobs, testing"},
                {"action": "create_spot_node_pool", "priority": "Spot"},
                {"action": "set_max_price", "value": "-1 for pay-as-you-go"},
                {
                    "action": "configure_node_labels",
                    "label": "kubernetes.azure.com/scalesetpriority=spot",
                },
                {"action": "update_pod_specs", "add": "nodeSelector and tolerations"},
            ],
            validation_steps=[
                "Test workload handles node evictions",
                "Monitor spot node availability in region",
                "Verify pod rescheduling works correctly",
                "Check workload completion rates",
            ],
            rollback_plan="Remove spot node pool and reschedule pods to regular nodes",
        )

    def _suggest_serverless_compute(
        self,
        resource: dict[str, Any],
        monthly_cost: float,
    ) -> OptimizationRecommendation | None:
        return OptimizationRecommendation(
            id=f"opt-sql-{resource['name']}-serverless",
            resource_id=resource["id"],
            resource_type="SQL Database",
            recommendation_type="serverless_compute",
            description="Switch to serverless compute tier for variable workloads",
            estimated_monthly_savings=monthly_cost * 0.5,
            estimated_savings_percentage=50.0,
            implementation_effort="medium",
            risk_level="low",
            actions=[
                {"action": "analyze_usage_patterns", "focus": "idle periods"},
                {"action": "calculate_serverless_cost", "based_on": "actual usage"},
                {"action": "migrate_to_serverless", "tier": "General Purpose Serverless"},
                {"action": "configure_auto_pause", "delay": "1 hour of inactivity"},
                {"action": "set_min_max_vcores", "range": "0.5 to 4 vCores"},
            ],
            validation_steps=[
                "Monitor auto-pause and resume behavior",
                "Check first-query latency after resume",
                "Verify cost savings match estimates",
                "Test application connection retry logic",
            ],
            rollback_plan="Switch back to provisioned compute tier",
        )

    async def get_optimization_summary(
        self,
        subscription_id: str,
        strategy: OptimizationStrategy = OptimizationStrategy.BALANCED,
    ) -> dict[str, Any]:
        """Generate a summary of all optimization opportunities."""
        recommendations = await self.analyze_optimization_opportunities(
            subscription_id, strategy, min_savings_threshold=0
        )

        total_savings = sum(r.estimated_monthly_savings for r in recommendations)

        by_type: dict[str, dict[str, Any]] = {}
        for rec in recommendations:
            if rec.recommendation_type not in by_type:
                by_type[rec.recommendation_type] = {
                    "count": 0,
                    "total_savings": 0.0,
                    "recommendations": [],
                }
            by_type[rec.recommendation_type]["count"] += 1
            by_type[rec.recommendation_type]["total_savings"] += rec.estimated_monthly_savings
            by_type[rec.recommendation_type]["recommendations"].append(rec.id)

        by_effort = {"low": [], "medium": [], "high": []}
        for rec in recommendations:
            by_effort[rec.implementation_effort].append(
                {"id": rec.id, "savings": rec.estimated_monthly_savings, "risk": rec.risk_level}
            )

        return {
            "total_recommendations": len(recommendations),
            "total_monthly_savings": total_savings,
            "total_annual_savings": total_savings * 12,
            "by_type": by_type,
            "by_effort": by_effort,
            "top_5_opportunities": [
                {
                    "id": r.id,
                    "resource": r.resource_id,
                    "type": r.recommendation_type,
                    "savings": r.estimated_monthly_savings,
                    "effort": r.implementation_effort,
                    "risk": r.risk_level,
                }
                for r in recommendations[:5]
            ],
            "quick_wins": [
                {"id": r.id, "savings": r.estimated_monthly_savings, "description": r.description}
                for r in recommendations
                if r.implementation_effort == "low" and r.risk_level == "low"
            ][:10],
        }

    async def simulate_optimization_impact(
        self,
        recommendations: list[OptimizationRecommendation],
        implementation_percentage: float = 100.0,
    ) -> dict[str, Any]:
        """Simulate the impact of implementing optimization recommendations."""
        selected_count = int(len(recommendations) * (implementation_percentage / 100))
        selected = recommendations[:selected_count]

        total_savings = sum(r.estimated_monthly_savings for r in selected)

        timeline = []
        cumulative_savings = 0.0
        for month in range(1, 13):
            cumulative_savings += total_savings
            timeline.append(
                {
                    "month": month,
                    "monthly_savings": total_savings,
                    "cumulative_savings": cumulative_savings,
                }
            )

        by_risk = {"low": 0.0, "medium": 0.0, "high": 0.0}
        for rec in selected:
            by_risk[rec.risk_level] += rec.estimated_monthly_savings

        return {
            "recommendations_implemented": selected_count,
            "total_recommendations": len(recommendations),
            "implementation_percentage": implementation_percentage,
            "monthly_savings": total_savings,
            "annual_savings": total_savings * 12,
            "savings_by_risk": by_risk,
            "savings_timeline": timeline,
            "roi_months": 3,
            "implementation_effort": {
                "low": sum(1 for r in selected if r.implementation_effort == "low"),
                "medium": sum(1 for r in selected if r.implementation_effort == "medium"),
                "high": sum(1 for r in selected if r.implementation_effort == "high"),
            },
        }
