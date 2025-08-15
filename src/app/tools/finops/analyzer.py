from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class CostOptimizationStrategy(Enum):
    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"
    CONSERVATIVE = "conservative"
    CUSTOM = "custom"


class ResourceCategory(Enum):
    COMPUTE = "compute"
    STORAGE = "storage"
    NETWORK = "network"
    DATABASE = "database"
    ANALYTICS = "analytics"
    AI_ML = "ai_ml"
    SECURITY = "security"
    MONITORING = "monitoring"
    BACKUP = "backup"
    OTHER = "other"


@dataclass
class ResourceCost:
    resource_id: str
    resource_name: str
    resource_type: str
    category: ResourceCategory
    location: str
    daily_cost: float
    monthly_cost: float
    yearly_cost: float
    currency: str = "USD"
    tags: dict[str, str] = field(default_factory=dict)
    optimization_potential: float = 0.0
    recommendations: list[str] = field(default_factory=list)


@dataclass
class CostAlert:
    id: str
    name: str
    threshold: float
    current_value: float
    percentage_used: float
    alert_type: str
    severity: str
    triggered_at: datetime
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CostForecast:
    period: str
    start_date: datetime
    end_date: datetime
    predicted_cost: float
    confidence_interval: tuple[float, float]
    trend: str
    anomalies: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OptimizationRecommendation:
    id: str
    resource_id: str
    recommendation_type: str
    description: str
    estimated_savings: float
    estimated_savings_percentage: float
    implementation_effort: str
    risk_level: str
    steps: list[str]
    prerequisites: list[str] = field(default_factory=list)
    impact: dict[str, Any] = field(default_factory=dict)


class CostManagementSystem:
    def __init__(self) -> None:
        self.cost_analyzer = CostAnalyzer()
        self.optimizer = CostOptimizer()
        self.forecaster = CostForecaster()
        self.alert_manager = AlertManager()
        self.budget_manager = BudgetManager()
        self.chargeback_system = ChargebackSystem()

    async def analyze_costs(
        self,
        subscription_id: str,
        start_date: datetime,
        end_date: datetime,
        group_by: list[str] | None = None,
    ) -> dict[str, Any]:
        resources = await self._fetch_resources(subscription_id)
        costs = await self.cost_analyzer.analyze(resources, start_date, end_date)

        analysis = {
            "total_cost": sum(c.monthly_cost for c in costs),
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "breakdown_by_category": self._group_by_category(costs),
            "breakdown_by_location": self._group_by_location(costs),
            "breakdown_by_resource_type": self._group_by_resource_type(costs),
            "top_expensive_resources": self._get_top_expensive(costs, 10),
            "optimization_potential": sum(c.optimization_potential for c in costs),
            "trends": await self.forecaster.analyze_trends(costs),
        }

        if group_by:
            for group in group_by:
                if group == "tags":
                    analysis[f"breakdown_by_{group}"] = self._group_by_tags(costs)
                elif group == "department":
                    analysis[f"breakdown_by_{group}"] = self._group_by_department(costs)
                elif group == "project":
                    analysis[f"breakdown_by_{group}"] = self._group_by_project(costs)

        return analysis

    async def get_optimization_recommendations(
        self,
        subscription_id: str,
        strategy: CostOptimizationStrategy = CostOptimizationStrategy.BALANCED,
        min_savings_threshold: float = 50.0,
    ) -> list[OptimizationRecommendation]:
        resources = await self._fetch_resources(subscription_id)
        recommendations = await self.optimizer.generate_recommendations(
            resources,
            strategy,
            min_savings_threshold,
        )

        return sorted(recommendations, key=lambda r: r.estimated_savings, reverse=True)

    async def forecast_costs(
        self,
        subscription_id: str,
        period_days: int = 30,
        include_growth_factor: bool = True,
    ) -> CostForecast:
        historical_data = await self._fetch_historical_costs(subscription_id, days=90)
        forecast = await self.forecaster.forecast(
            historical_data,
            period_days,
            include_growth_factor,
        )

        return forecast

    async def set_budget_alert(
        self,
        subscription_id: str,
        budget_amount: float,
        alert_thresholds: list[float] | None = None,
        recipients: list[str] | None = None,
    ) -> dict[str, Any]:
        if alert_thresholds is None:
            alert_thresholds = [50, 75, 90, 100]

        alert_config = await self.alert_manager.create_budget_alert(
            subscription_id,
            budget_amount,
            alert_thresholds,
            recipients or [],
        )

        return alert_config

    async def check_anomalies(
        self,
        subscription_id: str,
        sensitivity: str = "medium",
    ) -> list[dict[str, Any]]:
        costs = await self._fetch_recent_costs(subscription_id, days=30)
        anomalies = await self.cost_analyzer.detect_anomalies(costs, sensitivity)

        return anomalies

    async def generate_chargeback_report(
        self,
        subscription_id: str,
        period: tuple[datetime, datetime],
        allocation_method: str = "tags",
    ) -> dict[str, Any]:
        costs = await self._fetch_costs_for_period(subscription_id, period)
        report = await self.chargeback_system.generate_report(
            costs,
            allocation_method,
            period,
        )

        return report

    async def apply_optimization(
        self,
        recommendation: OptimizationRecommendation,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        if dry_run:
            return {
                "status": "dry_run",
                "recommendation_id": recommendation.id,
                "estimated_savings": recommendation.estimated_savings,
                "actions": recommendation.steps,
            }

        result = await self.optimizer.apply_recommendation(recommendation)

        return result

    async def get_cost_insights(
        self,
        subscription_id: str,
    ) -> dict[str, Any]:
        current_month_costs = await self._get_current_month_costs(subscription_id)
        last_month_costs = await self._get_last_month_costs(subscription_id)

        change_percentage = (
            (current_month_costs - last_month_costs) / last_month_costs * 100
            if last_month_costs > 0
            else 0
        )

        insights = {
            "current_month_spend": current_month_costs,
            "last_month_spend": last_month_costs,
            "month_over_month_change": change_percentage,
            "projected_month_end_spend": await self._project_month_end(subscription_id),
            "unused_resources": await self._identify_unused_resources(subscription_id),
            "overprovisioned_resources": await self._identify_overprovisioned(subscription_id),
            "reserved_instance_coverage": await self._get_ri_coverage(subscription_id),
            "spot_instance_usage": await self._get_spot_usage(subscription_id),
            "cost_saving_opportunities": await self._identify_quick_wins(subscription_id),
        }

        return insights

    def _group_by_category(self, costs: list[ResourceCost]) -> dict[str, float]:
        grouped: dict[str, float] = {}
        for cost in costs:
            category = cost.category.value
            grouped[category] = grouped.get(category, 0) + cost.monthly_cost
        return grouped

    def _group_by_location(self, costs: list[ResourceCost]) -> dict[str, float]:
        grouped: dict[str, float] = {}
        for cost in costs:
            grouped[cost.location] = grouped.get(cost.location, 0) + cost.monthly_cost
        return grouped

    def _group_by_resource_type(self, costs: list[ResourceCost]) -> dict[str, float]:
        grouped: dict[str, float] = {}
        for cost in costs:
            grouped[cost.resource_type] = grouped.get(cost.resource_type, 0) + cost.monthly_cost
        return grouped

    def _group_by_tags(self, costs: list[ResourceCost]) -> dict[str, dict[str, float]]:
        grouped: dict[str, dict[str, float]] = {}
        for cost in costs:
            for tag_key, tag_value in cost.tags.items():
                if tag_key not in grouped:
                    grouped[tag_key] = {}
                grouped[tag_key][tag_value] = grouped[tag_key].get(tag_value, 0) + cost.monthly_cost
        return grouped

    def _group_by_department(self, costs: list[ResourceCost]) -> dict[str, float]:
        grouped: dict[str, float] = {}
        for cost in costs:
            dept = cost.tags.get("department", "unassigned")
            grouped[dept] = grouped.get(dept, 0) + cost.monthly_cost
        return grouped

    def _group_by_project(self, costs: list[ResourceCost]) -> dict[str, float]:
        grouped: dict[str, float] = {}
        for cost in costs:
            project = cost.tags.get("project", "unassigned")
            grouped[project] = grouped.get(project, 0) + cost.monthly_cost
        return grouped

    def _get_top_expensive(self, costs: list[ResourceCost], limit: int) -> list[dict[str, Any]]:
        sorted_costs = sorted(costs, key=lambda c: c.monthly_cost, reverse=True)
        return [
            {
                "resource_id": c.resource_id,
                "resource_name": c.resource_name,
                "resource_type": c.resource_type,
                "monthly_cost": c.monthly_cost,
                "optimization_potential": c.optimization_potential,
            }
            for c in sorted_costs[:limit]
        ]

    async def _fetch_resources(self, subscription_id: str) -> list[dict[str, Any]]:
        return []

    async def _fetch_historical_costs(
        self, subscription_id: str, days: int
    ) -> list[dict[str, Any]]:
        return []

    async def _fetch_recent_costs(self, subscription_id: str, days: int) -> list[ResourceCost]:
        return []

    async def _fetch_costs_for_period(
        self,
        subscription_id: str,
        period: tuple[datetime, datetime],
    ) -> list[ResourceCost]:
        return []

    async def _get_current_month_costs(self, subscription_id: str) -> float:
        return 0.0

    async def _get_last_month_costs(self, subscription_id: str) -> float:
        return 0.0

    async def _project_month_end(self, subscription_id: str) -> float:
        return 0.0

    async def _identify_unused_resources(self, subscription_id: str) -> list[dict[str, Any]]:
        return []

    async def _identify_overprovisioned(self, subscription_id: str) -> list[dict[str, Any]]:
        return []

    async def _get_ri_coverage(self, subscription_id: str) -> float:
        return 0.0

    async def _get_spot_usage(self, subscription_id: str) -> float:
        return 0.0

    async def _identify_quick_wins(self, subscription_id: str) -> list[dict[str, Any]]:
        return []


class CostAnalyzer:
    async def analyze(
        self,
        resources: list[dict[str, Any]],
        start_date: datetime,
        end_date: datetime,
    ) -> list[ResourceCost]:
        costs: list[ResourceCost] = []
        for resource in resources:
            cost = await self._calculate_resource_cost(resource, start_date, end_date)
            costs.append(cost)
        return costs

    async def detect_anomalies(
        self,
        costs: list[ResourceCost],
        sensitivity: str,
    ) -> list[dict[str, Any]]:
        anomalies: list[dict[str, Any]] = []
        threshold = self._get_sensitivity_threshold(sensitivity)

        for cost in costs:
            if self._is_anomaly(cost, threshold):
                anomalies.append(
                    {
                        "resource_id": cost.resource_id,
                        "resource_name": cost.resource_name,
                        "anomaly_type": "cost_spike",
                        "severity": ("high" if cost.monthly_cost > threshold * 2 else "medium"),
                        "details": {
                            "current_cost": cost.monthly_cost,
                            "expected_range": (threshold * 0.8, threshold * 1.2),
                        },
                    }
                )

        return anomalies

    async def _calculate_resource_cost(
        self,
        resource: dict[str, Any],
        start_date: datetime,
        end_date: datetime,
    ) -> ResourceCost:
        base_cost = self._get_base_cost(resource["type"])
        location_multiplier = self._get_location_multiplier(resource.get("location", "westeurope"))

        daily_cost = base_cost * location_multiplier
        days = (end_date - start_date).days or 1

        return ResourceCost(
            resource_id=resource.get("id", ""),
            resource_name=resource.get("name", ""),
            resource_type=resource.get("type", ""),
            category=self._categorize_resource(resource.get("type", "")),
            location=resource.get("location", "westeurope"),
            daily_cost=daily_cost,
            monthly_cost=daily_cost * days,
            yearly_cost=daily_cost * 365,
            tags=resource.get("tags", {}),
            optimization_potential=daily_cost * 0.3,
            recommendations=self._generate_basic_recommendations(resource),
        )

    def _get_base_cost(self, resource_type: str) -> float:
        costs = {
            "Microsoft.Compute/virtualMachines": 50.0,
            "Microsoft.Storage/storageAccounts": 25.0,
            "Microsoft.ContainerService/managedClusters": 200.0,
            "Microsoft.Web/sites": 30.0,
            "Microsoft.Sql/servers": 150.0,
            "Microsoft.KeyVault/vaults": 5.0,
            "Microsoft.Network/virtualNetworks": 10.0,
            "Microsoft.Network/loadBalancers": 20.0,
            "Microsoft.Network/applicationGateways": 40.0,
        }
        return costs.get(resource_type, 20.0)

    def _get_location_multiplier(self, location: str) -> float:
        multipliers = {
            "westeurope": 1.0,
            "northeurope": 0.95,
            "eastus": 0.9,
            "westus": 0.92,
            "centralus": 0.88,
            "uksouth": 1.05,
            "southeastasia": 0.85,
        }
        return multipliers.get(location, 1.0)

    def _categorize_resource(self, resource_type: str) -> ResourceCategory:
        if "Compute" in resource_type or "VirtualMachines" in resource_type:
            return ResourceCategory.COMPUTE
        elif "Storage" in resource_type:
            return ResourceCategory.STORAGE
        elif "Network" in resource_type:
            return ResourceCategory.NETWORK
        elif "Sql" in resource_type or "Database" in resource_type:
            return ResourceCategory.DATABASE
        elif "Analytics" in resource_type or "Synapse" in resource_type:
            return ResourceCategory.ANALYTICS
        elif "CognitiveServices" in resource_type:
            return ResourceCategory.AI_ML
        elif "KeyVault" in resource_type or "Security" in resource_type:
            return ResourceCategory.SECURITY
        elif "Monitor" in resource_type or "Insights" in resource_type:
            return ResourceCategory.MONITORING
        elif "Backup" in resource_type or "RecoveryServices" in resource_type:
            return ResourceCategory.BACKUP
        else:
            return ResourceCategory.OTHER

    def _generate_basic_recommendations(self, resource: dict[str, Any]) -> list[str]:
        recommendations: list[str] = []

        if resource.get("type") == "Microsoft.Compute/virtualMachines":
            recommendations.append("Consider using Reserved Instances for 1-3 year commitment")
            recommendations.append("Enable auto-shutdown for non-production VMs")
            recommendations.append("Review VM sizing potential for downsizing")
        elif resource.get("type") == "Microsoft.Storage/storageAccounts":
            recommendations.append("Move infrequently accessed data to Cool or Archive tier")
            recommendations.append("Enable lifecycle management policies")
            recommendations.append("Review and delete unused blob containers")

        return recommendations

    def _get_sensitivity_threshold(self, sensitivity: str) -> float:
        thresholds = {
            "low": 1000.0,
            "medium": 500.0,
            "high": 100.0,
        }
        return thresholds.get(sensitivity, 500.0)

    def _is_anomaly(self, cost: ResourceCost, threshold: float) -> bool:
        return cost.monthly_cost > threshold * 1.5


class CostOptimizer:
    async def generate_recommendations(
        self,
        resources: list[dict[str, Any]],
        strategy: CostOptimizationStrategy,
        min_savings_threshold: float,
    ) -> list[OptimizationRecommendation]:
        recommendations: list[OptimizationRecommendation] = []

        for resource in resources:
            resource_recommendations = await self._analyze_resource(resource, strategy)
            for rec in resource_recommendations:
                if rec.estimated_savings >= min_savings_threshold:
                    recommendations.append(rec)

        return recommendations

    async def apply_recommendation(
        self,
        recommendation: OptimizationRecommendation,
    ) -> dict[str, Any]:
        return {
            "status": "applied",
            "recommendation_id": recommendation.id,
            "actual_savings": recommendation.estimated_savings * 0.9,
            "implementation_time": datetime.utcnow().isoformat(),
        }

    async def _analyze_resource(
        self,
        resource: dict[str, Any],
        strategy: CostOptimizationStrategy,
    ) -> list[OptimizationRecommendation]:
        recommendations: list[OptimizationRecommendation] = []

        if resource.get("type") == "Microsoft.Compute/virtualMachines":
            recommendations.extend(await self._analyze_vm(resource, strategy))
        elif resource.get("type") == "Microsoft.Storage/storageAccounts":
            recommendations.extend(await self._analyze_storage(resource, strategy))
        elif resource.get("type") == "Microsoft.ContainerService/managedClusters":
            recommendations.extend(await self._analyze_aks(resource, strategy))

        return recommendations

    async def _analyze_vm(
        self,
        resource: dict[str, Any],
        strategy: CostOptimizationStrategy,
    ) -> list[OptimizationRecommendation]:
        recommendations: list[OptimizationRecommendation] = []

        recommendations.append(
            OptimizationRecommendation(
                id=f"opt-{resource.get('id', '')}-ri",
                resource_id=resource.get("id", ""),
                recommendation_type="reserved_instance",
                description="Purchase 1-year Reserved Instance for production VM",
                estimated_savings=1000.0,
                estimated_savings_percentage=40.0,
                implementation_effort="low",
                risk_level="low",
                steps=[
                    "Review VM usage patterns",
                    "Confirm long-term commitment",
                    "Purchase Reserved Instance",
                    "Apply to VM",
                ],
                prerequisites=["VM must be running 24/7"],
                impact={"availability": "none", "performance": "none"},
            )
        )

        if strategy == CostOptimizationStrategy.AGGRESSIVE:
            recommendations.append(
                OptimizationRecommendation(
                    id=f"opt-{resource.get('id', '')}-spot",
                    resource_id=resource.get("id", ""),
                    recommendation_type="spot_instance",
                    description="Convert to Spot Instance for non-critical workloads",
                    estimated_savings=1500.0,
                    estimated_savings_percentage=60.0,
                    implementation_effort="medium",
                    risk_level="high",
                    steps=[
                        "Verify workload is interruptible",
                        "Implement graceful shutdown handling",
                        "Convert to Spot Instance",
                    ],
                    prerequisites=["Workload must tolerate interruptions"],
                    impact={"availability": "reduced", "performance": "none"},
                )
            )

        return recommendations

    async def _analyze_storage(
        self,
        resource: dict[str, Any],
        strategy: CostOptimizationStrategy,
    ) -> list[OptimizationRecommendation]:
        return [
            OptimizationRecommendation(
                id=f"opt-{resource.get('id', '')}-tier",
                resource_id=resource.get("id", ""),
                recommendation_type="storage_tiering",
                description="Move cold data to Archive tier",
                estimated_savings=200.0,
                estimated_savings_percentage=30.0,
                implementation_effort="low",
                risk_level="low",
                steps=[
                    "Identify cold data",
                    "Create lifecycle management policy",
                    "Monitor transition",
                ],
                prerequisites=["Data access patterns analyzed"],
                impact={"availability": "delayed_access", "performance": "reduced"},
            )
        ]

    async def _analyze_aks(
        self,
        resource: dict[str, Any],
        strategy: CostOptimizationStrategy,
    ) -> list[OptimizationRecommendation]:
        return [
            OptimizationRecommendation(
                id=f"opt-{resource.get('id', '')}-autoscale",
                resource_id=resource.get("id", ""),
                recommendation_type="autoscaling",
                description="Enable cluster autoscaler with optimal limits",
                estimated_savings=500.0,
                estimated_savings_percentage=25.0,
                implementation_effort="medium",
                risk_level="medium",
                steps=[
                    "Analyze workload patterns",
                    "Configure autoscaler",
                    "Set min/max node counts",
                    "Test scaling behavior",
                ],
                prerequisites=["Monitoring enabled"],
                impact={"availability": "improved", "performance": "dynamic"},
            )
        ]


class CostForecaster:
    async def forecast(
        self,
        historical_data: list[dict[str, Any]],
        period_days: int,
        include_growth_factor: bool,
    ) -> CostForecast:
        base_prediction = self._calculate_base_prediction(historical_data)
        growth_factor = 1.05 if include_growth_factor else 1.0

        predicted_cost = base_prediction * period_days * growth_factor
        confidence_interval = (predicted_cost * 0.9, predicted_cost * 1.1)

        return CostForecast(
            period=f"{period_days} days",
            start_date=datetime.utcnow(),
            end_date=datetime.utcnow() + timedelta(days=period_days),
            predicted_cost=predicted_cost,
            confidence_interval=confidence_interval,
            trend="increasing" if include_growth_factor else "stable",
            anomalies=[],
        )

    async def analyze_trends(self, costs: list[ResourceCost]) -> dict[str, Any]:
        return {
            "overall_trend": "increasing",
            "growth_rate": 5.2,
            "seasonal_patterns": ["higher_q4", "lower_q2"],
            "outliers": [],
        }

    def _calculate_base_prediction(self, historical_data: list[dict[str, Any]]) -> float:
        if not historical_data:
            return 100.0

        total = sum(d.get("cost", 0) for d in historical_data)
        return total / len(historical_data) if historical_data else 100.0


class AlertManager:
    async def create_budget_alert(
        self,
        subscription_id: str,
        budget_amount: float,
        alert_thresholds: list[float],
        recipients: list[str],
    ) -> dict[str, Any]:
        return {
            "alert_id": f"alert-{subscription_id}-{datetime.utcnow().timestamp()}",
            "budget_amount": budget_amount,
            "thresholds": alert_thresholds,
            "recipients": recipients,
            "status": "active",
            "created_at": datetime.utcnow().isoformat(),
        }


class BudgetManager:
    async def set_budget(
        self,
        subscription_id: str,
        amount: float,
        period: str,
    ) -> dict[str, Any]:
        return {
            "budget_id": f"budget-{subscription_id}",
            "amount": amount,
            "period": period,
            "status": "active",
        }


class ChargebackSystem:
    async def generate_report(
        self,
        costs: list[ResourceCost],
        allocation_method: str,
        period: tuple[datetime, datetime],
    ) -> dict[str, Any]:
        allocations: dict[str, float] = {}

        for cost in costs:
            key = cost.tags.get(allocation_method, "unallocated")
            allocations[key] = allocations.get(key, 0) + cost.monthly_cost

        return {
            "period": {
                "start": period[0].isoformat(),
                "end": period[1].isoformat(),
            },
            "allocation_method": allocation_method,
            "allocations": allocations,
            "total": sum(allocations.values()),
        }
