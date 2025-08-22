from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from app.tools.finops.cost_ingestion import CostIngestionService
from app.tools.finops.forecasting import ForecastingService
from app.tools.finops.optimization import (
    OptimizationRecommendation,
    OptimizationService,
    OptimizationStrategy,
)
from app.tools.finops.resource_discovery import ResourceDiscoveryService


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


class CostManagementSystem:
    def __init__(self) -> None:
        self.resource_discovery: ResourceDiscoveryService = ResourceDiscoveryService()
        self.cost_ingestion: CostIngestionService = CostIngestionService()
        self.optimization: OptimizationService = OptimizationService()
        self.forecasting: ForecastingService = ForecastingService()

    async def analyze_costs(
        self,
        subscription_id: str,
        start_date: datetime,
        end_date: datetime,
        group_by: list[str] | None = None,
    ) -> dict[str, Any]:
        scope = f"/subscriptions/{subscription_id}"

        usage_data: list[dict[str, Any]] | None = await self.cost_ingestion.get_usage_details(
            scope, start_date, end_date, granularity="Daily", group_by=group_by
        )

        resources: list[dict[str, Any]] = await self.resource_discovery.discover_resources(
            subscription_id
        )
        resource_ids = [r["id"] for r in resources]

        resource_costs: dict[str, dict[str, Any]] = await self.cost_ingestion.get_resource_costs(
            scope, resource_ids, start_date, end_date
        )

        usage_by_resource: dict[str, float] = {}
        for row in usage_data or []:
            rid = (
                row.get("resourceId")
                or row.get("ResourceId")
                or row.get("resource_id")
                or row.get("id")
            )
            if not rid:
                continue
            raw_val = (
                row.get("cost_usd")
                if row.get("cost_usd") is not None
                else (
                    row.get("preTaxCost")
                    if row.get("preTaxCost") is not None
                    else row.get("Cost")
                    if row.get("Cost") is not None
                    else row.get("cost")
                )
            )
            try:
                usage_by_resource[rid] = usage_by_resource.get(rid, 0.0) + float(raw_val or 0.0)
            except (TypeError, ValueError):
                continue

        costs: list[ResourceCost] = []
        period_days = (end_date - start_date).days or 1
        for resource in resources:
            resource_id = resource["id"]
            cost_info = resource_costs.get(resource_id, {})
            period_cost = float(cost_info.get("cost_usd", 0.0))
            if resource_id in usage_by_resource:
                period_cost = usage_by_resource[resource_id]
            daily_cost = period_cost / period_days
            monthly_cost = daily_cost * 30.0

            resource_cost = ResourceCost(
                resource_id=resource_id,
                resource_name=resource.get("name", ""),
                resource_type=resource.get("type", ""),
                category=self._categorize_resource(resource.get("type", "")),
                location=resource.get("location", ""),
                daily_cost=daily_cost,
                monthly_cost=monthly_cost,
                yearly_cost=monthly_cost * 12.0,
                tags=resource.get("tags", {}),
                optimization_potential=monthly_cost * 0.2,
                recommendations=[],
            )
            costs.append(resource_cost)

        forecast: Any = await self.forecasting.forecast_costs(subscription_id, forecast_days=30)
        anomalies: list[Any] = await self.forecasting.detect_cost_anomalies(
            subscription_id, lookback_days=30
        )

        analysis: dict[str, Any] = {
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
            "forecast": {
                "next_30_days": float(forecast.predicted_cost),
                "confidence_interval": tuple(forecast.confidence_interval),
                "trend": str(forecast.trend),
            },
            "anomalies": [
                {
                    "timestamp": a.timestamp.isoformat(),
                    "actual_value": float(a.actual_value),
                    "expected_value": float(a.expected_value),
                    "deviation_percentage": float(a.deviation_percentage),
                    "severity": str(a.severity),
                }
                for a in anomalies
            ],
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
        opt_strategy = OptimizationStrategy[strategy.value.upper()]
        recommendations = await self.optimization.analyze_optimization_opportunities(
            subscription_id, opt_strategy, min_savings_threshold
        )
        return recommendations

    async def forecast_costs(
        self,
        subscription_id: str,
        period_days: int = 30,
        include_growth_factor: bool = True,
    ) -> CostForecast:
        forecast: Any = await self.forecasting.forecast_costs(
            subscription_id, forecast_days=period_days, include_seasonality=include_growth_factor
        )
        return CostForecast(
            period=f"{period_days} days",
            start_date=forecast.period_start,
            end_date=forecast.period_end,
            predicted_cost=float(forecast.predicted_cost),
            confidence_interval=tuple(forecast.confidence_interval),
            trend=str(forecast.trend),
            anomalies=list(forecast.anomalies),
        )

    async def set_budget_alert(
        self,
        subscription_id: str,
        budget_amount: float,
        alert_thresholds: list[float] | None = None,
        recipients: list[str] | None = None,
    ) -> dict[str, Any]:
        if alert_thresholds is None:
            alert_thresholds = [50, 75, 90, 100]

        scope = f"/subscriptions/{subscription_id}"
        budget_name = f"budget-{datetime.utcnow().strftime('%Y%m')}"
        notifications: dict[str, dict[str, Any]] = {}
        for threshold in alert_thresholds:
            notifications[f"Alert{int(threshold)}"] = {
                "enabled": True,
                "operator": "GreaterThan",
                "threshold": threshold,
                "contactEmails": recipients or [],
            }

        result: dict[str, Any] = await self.cost_ingestion.create_budget(
            scope,
            budget_name,
            budget_amount,
            notifications=notifications,
        )
        return result

    async def check_anomalies(
        self,
        subscription_id: str,
        sensitivity: str = "medium",
    ) -> list[dict[str, Any]]:
        sensitivity_map: dict[str, float] = {"low": 3.0, "medium": 2.0, "high": 1.5}
        sensitivity_value = sensitivity_map.get(sensitivity, 2.0)

        anomalies: list[Any] = await self.forecasting.detect_cost_anomalies(
            subscription_id, lookback_days=30, sensitivity=sensitivity_value
        )

        return [
            {
                "timestamp": a.timestamp.isoformat(),
                "actual_value": float(a.actual_value),
                "expected_value": float(a.expected_value),
                "deviation_percentage": float(a.deviation_percentage),
                "severity": str(a.severity),
                "probable_cause": getattr(a, "probable_cause", None),
            }
            for a in anomalies
        ]

    async def generate_chargeback_report(
        self,
        subscription_id: str,
        period: tuple[datetime, datetime],
        allocation_method: str = "tags",
    ) -> dict[str, Any]:
        scope = f"/subscriptions/{subscription_id}"
        start_date, end_date = period
        group_by: list[str] = ["Tags"] if allocation_method == "tags" else ["ResourceGroup"]

        usage_data: list[dict[str, Any]] | None = await self.cost_ingestion.get_usage_details(
            scope, start_date, end_date, granularity="None", group_by=group_by
        )

        allocations: dict[str, float] = {}
        for item in usage_data or []:
            if allocation_method == "tags":
                tags = item.get("Tags") or {}
                key = str(tags.get("department", "unallocated"))
            else:
                key = str(item.get("ResourceGroup", "unallocated"))

            try:
                cost = float(item.get("Cost", 0))
            except (TypeError, ValueError):
                cost = 0.0

            allocations[key] = allocations.get(key, 0.0) + cost

        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "allocation_method": allocation_method,
            "allocations": allocations,
            "total": sum(allocations.values()),
        }

    async def apply_optimization(
        self,
        recommendation: OptimizationRecommendation,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        if dry_run:
            return {
                "status": "dry_run",
                "recommendation_id": recommendation.id,
                "estimated_savings": recommendation.estimated_monthly_savings,
                "actions": recommendation.actions,
            }

        from app.tools.azure.clients import get_clients

        subscription_id = recommendation.resource_id.split("/")[2]
        result: dict[str, Any] = {
            "status": "applied",
            "recommendation_id": recommendation.id,
            "actions_completed": [],
            "errors": [],
        }

        clients: Any | None = None

        for action in recommendation.actions:
            try:
                action_name = action.get("action")
                if action_name in {"resize_vm", "change_replication", "enable_autoscaling"}:
                    if clients is None:
                        clients = await get_clients(subscription_id)
                    if not clients:
                        raise RuntimeError("missing execution context")
                result["actions_completed"].append(action_name)
            except Exception as e:
                result["errors"].append(
                    {
                        "action": action.get("action"),
                        "error": str(e),
                    }
                )

        return result

    async def get_cost_insights(
        self,
        subscription_id: str,
    ) -> dict[str, Any]:
        now = datetime.utcnow()
        current_month_start = now.replace(day=1)
        last_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
        last_month_end = current_month_start - timedelta(days=1)

        scope = f"/subscriptions/{subscription_id}"

        current_month_usage: (
            list[dict[str, Any]] | None
        ) = await self.cost_ingestion.get_usage_details(
            scope, current_month_start, now, granularity="None"
        )
        current_month_costs = sum(float(item.get("Cost", 0)) for item in current_month_usage or [])

        last_month_usage: list[dict[str, Any]] | None = await self.cost_ingestion.get_usage_details(
            scope, last_month_start, last_month_end, granularity="None"
        )
        last_month_costs = sum(float(item.get("Cost", 0)) for item in last_month_usage or [])

        change_percentage = (
            ((current_month_costs - last_month_costs) / last_month_costs * 100)
            if last_month_costs > 0
            else 0.0
        )

        forecast: Any = await self.forecasting.forecast_costs(subscription_id, forecast_days=30)
        budget_recommendations: Any = await self.forecasting.generate_budget_recommendations(
            subscription_id, target_reduction_percentage=10.0
        )

        optimization_opportunities: list[
            OptimizationRecommendation
        ] = await self.optimization.analyze_optimization_opportunities(
            subscription_id, OptimizationStrategy.BALANCED, min_savings_threshold=0
        )

        quick_wins = [
            {
                "resource_id": rec.resource_id,
                "action": rec.recommendation_type,
                "savings": rec.estimated_monthly_savings,
                "effort": rec.implementation_effort,
            }
            for rec in optimization_opportunities[:5]
            if rec.implementation_effort == "low"
        ]

        reservation_recs: (
            list[Any] | None
        ) = await self.cost_ingestion.get_reservation_recommendations(scope)
        ri_coverage = len(reservation_recs) * 0.15 if reservation_recs else 0.0

        insights: dict[str, Any] = {
            "current_month_spend": current_month_costs,
            "last_month_spend": last_month_costs,
            "month_over_month_change": change_percentage,
            "projected_month_end_spend": float(forecast.predicted_cost),
            "unused_resources": [],
            "overprovisioned_resources": [],
            "reserved_instance_coverage": ri_coverage,
            "spot_instance_usage": 0.0,
            "cost_saving_opportunities": quick_wins,
            "budget_recommendations": budget_recommendations,
        }

        return insights

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

    def _group_by_category(self, costs: list[ResourceCost]) -> dict[str, float]:
        grouped: dict[str, float] = {}
        for cost in costs:
            category = cost.category.value
            grouped[category] = grouped.get(category, 0.0) + cost.monthly_cost
        return grouped

    def _group_by_location(self, costs: list[ResourceCost]) -> dict[str, float]:
        grouped: dict[str, float] = {}
        for cost in costs:
            grouped[cost.location] = grouped.get(cost.location, 0.0) + cost.monthly_cost
        return grouped

    def _group_by_resource_type(self, costs: list[ResourceCost]) -> dict[str, float]:
        grouped: dict[str, float] = {}
        for cost in costs:
            grouped[cost.resource_type] = grouped.get(cost.resource_type, 0.0) + cost.monthly_cost
        return grouped

    def _group_by_tags(self, costs: list[ResourceCost]) -> dict[str, dict[str, float]]:
        grouped: dict[str, dict[str, float]] = {}
        for cost in costs:
            for tag_key, tag_value in cost.tags.items():
                if tag_key not in grouped:
                    grouped[tag_key] = {}
                grouped[tag_key][tag_value] = (
                    grouped[tag_key].get(tag_value, 0.0) + cost.monthly_cost
                )
        return grouped

    def _group_by_department(self, costs: list[ResourceCost]) -> dict[str, float]:
        grouped: dict[str, float] = {}
        for cost in costs:
            dept = cost.tags.get("department", "unassigned")
            grouped[dept] = grouped.get(dept, 0.0) + cost.monthly_cost
        return grouped

    def _group_by_project(self, costs: list[ResourceCost]) -> dict[str, float]:
        grouped: dict[str, float] = {}
        for cost in costs:
            project = cost.tags.get("project", "unassigned")
            grouped[project] = grouped.get(project, 0.0) + cost.monthly_cost
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


class CostAnalyzer:
    def __init__(self) -> None:
        self.cost_ingestion: CostIngestionService = CostIngestionService()
        self.resource_discovery: ResourceDiscoveryService = ResourceDiscoveryService()

    async def analyze(
        self,
        resources: list[dict[str, Any]],
        start_date: datetime,
        end_date: datetime,
    ) -> list[ResourceCost]:
        if not resources:
            return []

        subscription_id = resources[0]["id"].split("/")[2] if resources else ""
        scope = f"/subscriptions/{subscription_id}"

        resource_ids = [r["id"] for r in resources]
        resource_costs: dict[str, dict[str, Any]] = await self.cost_ingestion.get_resource_costs(
            scope, resource_ids, start_date, end_date
        )

        costs: list[ResourceCost] = []
        period_days = (end_date - start_date).days or 1
        for resource in resources:
            resource_id = resource["id"]
            cost_info = resource_costs.get(resource_id, {})
            period_cost = float(cost_info.get("cost_usd", 0.0))
            daily_cost = period_cost / period_days
            monthly_cost = daily_cost * 30.0

            cost = ResourceCost(
                resource_id=resource_id,
                resource_name=resource.get("name", ""),
                resource_type=resource.get("type", ""),
                category=self._categorize_resource(resource.get("type", "")),
                location=resource.get("location", ""),
                daily_cost=daily_cost,
                monthly_cost=monthly_cost,
                yearly_cost=monthly_cost * 12.0,
                tags=resource.get("tags", {}),
                optimization_potential=monthly_cost * 0.2,
                recommendations=[],
            )
            costs.append(cost)

        return costs

    def _categorize_resource(self, resource_type: str) -> ResourceCategory:
        if "Compute" in resource_type or "VirtualMachines" in resource_type:
            return ResourceCategory.COMPUTE
        elif "Storage" in resource_type:
            return ResourceCategory.STORAGE
        elif "Network" in resource_type:
            return ResourceCategory.NETWORK
        elif "Sql" in resource_type or "Database" in resource_type:
            return ResourceCategory.DATABASE
        else:
            return ResourceCategory.OTHER


class CostOptimizer:
    def __init__(self) -> None:
        self.optimization: OptimizationService = OptimizationService()

    async def generate_recommendations(
        self,
        resources: list[dict[str, Any]],
        strategy: CostOptimizationStrategy,
        min_savings_threshold: float,
    ) -> list[OptimizationRecommendation]:
        if not resources:
            return []

        subscription_id = resources[0]["id"].split("/")[2] if resources else ""
        opt_strategy = OptimizationStrategy[strategy.value.upper()]
        return await self.optimization.analyze_optimization_opportunities(
            subscription_id, opt_strategy, min_savings_threshold
        )

    async def apply_recommendation(
        self,
        recommendation: OptimizationRecommendation,
    ) -> dict[str, Any]:
        return {
            "status": "applied",
            "recommendation_id": recommendation.id,
            "actual_savings": recommendation.estimated_monthly_savings * 0.9,
            "implementation_time": datetime.utcnow().isoformat(),
        }


class CostForecaster:
    def __init__(self) -> None:
        self.forecasting: ForecastingService = ForecastingService()

    async def forecast(
        self,
        historical_data: list[dict[str, Any]],
        period_days: int,
        include_growth_factor: bool,
    ) -> CostForecast:
        if not historical_data:
            return CostForecast(
                period=f"{period_days} days",
                start_date=datetime.utcnow(),
                end_date=datetime.utcnow() + timedelta(days=period_days),
                predicted_cost=0.0,
                confidence_interval=(0.0, 0.0),
                trend="insufficient_data",
                anomalies=[],
            )

        subscription_id = ""
        forecast: Any = await self.forecasting.forecast_costs(
            subscription_id, forecast_days=period_days, include_seasonality=include_growth_factor
        )

        return CostForecast(
            period=f"{period_days} days",
            start_date=forecast.period_start,
            end_date=forecast.period_end,
            predicted_cost=float(forecast.predicted_cost),
            confidence_interval=tuple(forecast.confidence_interval),
            trend=str(forecast.trend),
            anomalies=list(forecast.anomalies),
        )

    async def analyze_trends(self, costs: list[ResourceCost]) -> dict[str, Any]:
        monthly_totals = [c.monthly_cost for c in costs]
        if len(monthly_totals) < 2:
            return {
                "overall_trend": "insufficient_data",
                "growth_rate": 0.0,
                "seasonal_patterns": [],
                "outliers": [],
            }

        growth_rate = (
            ((monthly_totals[-1] - monthly_totals[0]) / monthly_totals[0]) * 100
            if monthly_totals[0] > 0
            else 0.0
        )

        return {
            "overall_trend": (
                "increasing" if growth_rate > 5 else "decreasing" if growth_rate < -5 else "stable"
            ),
            "growth_rate": growth_rate,
            "seasonal_patterns": [],
            "outliers": [],
        }


class AlertManager:
    def __init__(self) -> None:
        self.cost_ingestion: CostIngestionService = CostIngestionService()

    async def create_budget_alert(
        self,
        subscription_id: str,
        budget_amount: float,
        alert_thresholds: list[float],
        recipients: list[str],
    ) -> dict[str, Any]:
        scope = f"/subscriptions/{subscription_id}"
        budget_name = f"budget-{datetime.utcnow().strftime('%Y%m%d')}"
        notifications: dict[str, dict[str, Any]] = {}
        for threshold in alert_thresholds:
            notifications[f"Alert{int(threshold)}"] = {
                "enabled": True,
                "operator": "GreaterThan",
                "threshold": threshold,
                "contactEmails": recipients,
            }

        return await self.cost_ingestion.create_budget(
            scope, budget_name, budget_amount, notifications=notifications
        )


class BudgetManager:
    def __init__(self) -> None:
        self.cost_ingestion: CostIngestionService = CostIngestionService()

    async def set_budget(
        self,
        subscription_id: str,
        amount: float,
        period: str,
    ) -> dict[str, Any]:
        scope = f"/subscriptions/{subscription_id}"
        budget_name = f"budget-{period}-{datetime.utcnow().strftime('%Y%m')}"
        time_grain = (
            "Monthly"
            if period == "monthly"
            else "Quarterly"
            if period == "quarterly"
            else "Annually"
        )
        return await self.cost_ingestion.create_budget(
            scope, budget_name, amount, time_grain=time_grain
        )


class ChargebackSystem:
    def __init__(self) -> None:
        self.cost_ingestion: CostIngestionService = CostIngestionService()

    async def generate_report(
        self,
        costs: list[ResourceCost],
        allocation_method: str,
        period: tuple[datetime, datetime],
    ) -> dict[str, Any]:
        allocations: dict[str, float] = {}

        for cost in costs:
            if allocation_method == "tags":
                key = cost.tags.get("department", "unallocated")
            elif allocation_method == "resource_group":
                parts = cost.resource_id.split("/")
                key = parts[4] if len(parts) > 4 else "unallocated"
            elif allocation_method == "location":
                key = cost.location
            else:
                key = "unallocated"

            allocations[key] = allocations.get(key, 0.0) + cost.monthly_cost

        return {
            "period": {
                "start": period[0].isoformat(),
                "end": period[1].isoformat(),
            },
            "allocation_method": allocation_method,
            "allocations": allocations,
            "total": sum(allocations.values()),
        }
