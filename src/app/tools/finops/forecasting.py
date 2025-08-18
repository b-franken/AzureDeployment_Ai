from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from scipy import stats
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures

from app.tools.finops.cost_ingestion import CostIngestionService


@dataclass
class CostForecast:
    period_start: datetime
    period_end: datetime
    predicted_cost: float
    confidence_interval: tuple[float, float]
    confidence_level: float
    trend: str
    seasonality_detected: bool
    anomalies: list[dict[str, Any]]
    model_accuracy: float


@dataclass
class AnomalyDetection:
    timestamp: datetime
    actual_value: float
    expected_value: float
    deviation_percentage: float
    severity: str
    probable_cause: str


class ForecastingService:
    def __init__(self):
        self.cost_ingestion = CostIngestionService()

    async def forecast_costs(
        self,
        subscription_id: str,
        forecast_days: int = 30,
        confidence_level: float = 0.95,
        include_seasonality: bool = True,
    ) -> CostForecast:
        historical_data = await self._get_historical_data(subscription_id, days=90)

        if not historical_data:
            return self._create_default_forecast(forecast_days)

        dates = [d["date"] for d in historical_data]
        costs = [d["cost"] for d in historical_data]

        X = np.array([(d - dates[0]).days for d in dates]).reshape(-1, 1)
        y = np.array(costs)

        if include_seasonality:
            model, accuracy = self._fit_seasonal_model(X, y)
            seasonality = self._detect_seasonality(y)
        else:
            model, accuracy = self._fit_trend_model(X, y)
            seasonality = False

        future_X = np.array(range(len(dates), len(dates) + forecast_days)).reshape(-1, 1)

        predictions = model.predict(future_X)

        std_error = np.std(y - model.predict(X))
        z_score = stats.norm.ppf((1 + confidence_level) / 2)
        margin = z_score * std_error

        total_predicted = float(np.sum(predictions))
        lower_bound = float(total_predicted - margin * forecast_days)
        upper_bound = float(total_predicted + margin * forecast_days)

        trend = self._determine_trend(predictions)
        anomalies = await self._detect_anomalies(historical_data, model, X)

        return CostForecast(
            period_start=datetime.utcnow(),
            period_end=datetime.utcnow() + timedelta(days=forecast_days),
            predicted_cost=total_predicted,
            confidence_interval=(lower_bound, upper_bound),
            confidence_level=confidence_level,
            trend=trend,
            seasonality_detected=seasonality,
            anomalies=anomalies,
            model_accuracy=accuracy,
        )

    async def detect_cost_anomalies(
        self,
        subscription_id: str,
        lookback_days: int = 30,
        sensitivity: float = 2.0,
    ) -> list[AnomalyDetection]:
        historical_data = await self._get_historical_data(subscription_id, days=lookback_days)

        if len(historical_data) < 7:
            return []

        dates = [d["date"] for d in historical_data]
        costs = [d["cost"] for d in historical_data]

        X = np.array([(d - dates[0]).days for d in dates]).reshape(-1, 1)
        y = np.array(costs)

        model, _ = self._fit_trend_model(X, y)
        predictions = model.predict(X)

        residuals = y - predictions
        std_residual = np.std(residuals)
        mean_residual = np.mean(residuals)

        anomalies = []
        for i, (date, actual, expected) in enumerate(zip(dates, costs, predictions, strict=False)):
            z_score = abs((actual - expected - mean_residual) / std_residual)

            if z_score > sensitivity:
                deviation = ((actual - expected) / expected) * 100

                anomaly = AnomalyDetection(
                    timestamp=date,
                    actual_value=float(actual),
                    expected_value=float(expected),
                    deviation_percentage=float(deviation),
                    severity=self._classify_severity(z_score),
                    probable_cause=await self._identify_probable_cause(
                        subscription_id, date, deviation
                    ),
                )
                anomalies.append(anomaly)

        return anomalies

    async def generate_budget_recommendations(
        self,
        subscription_id: str,
        target_reduction_percentage: float = 10.0,
    ) -> dict[str, Any]:
        current_month_cost = await self._get_current_month_cost(subscription_id)
        forecast = await self.forecast_costs(subscription_id, forecast_days=30)

        target_budget = current_month_cost * (1 - target_reduction_percentage / 100)

        recommendations = {
            "current_monthly_cost": current_month_cost,
            "forecasted_next_month": forecast.predicted_cost,
            "recommended_budget": target_budget,
            "confidence_level": forecast.confidence_level,
            "budget_thresholds": [
                {"percentage": 50, "action": "notification", "recipients": ["finance_team"]},
                {
                    "percentage": 75,
                    "action": "alert",
                    "recipients": ["finance_team", "engineering_leads"],
                },
                {"percentage": 90, "action": "critical_alert", "recipients": ["all_stakeholders"]},
                {"percentage": 100, "action": "cost_controls", "recipients": ["executives"]},
            ],
            "cost_reduction_strategies": await self._identify_reduction_strategies(
                subscription_id, target_reduction_percentage
            ),
        }

        return recommendations

    async def predict_cost_impact(
        self,
        subscription_id: str,
        resource_changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        current_costs = await self._get_current_costs_by_resource_type(subscription_id)

        impact_analysis = {
            "current_monthly_cost": sum(current_costs.values()),
            "changes": [],
            "total_impact": 0.0,
        }

        for change in resource_changes:
            resource_type = change["resource_type"]
            action = change["action"]
            quantity = change.get("quantity", 1)

            unit_cost = await self._get_resource_unit_cost(resource_type, change.get("sku"))

            if action == "add":
                monthly_impact = unit_cost * quantity * 30
            elif action == "remove":
                monthly_impact = -unit_cost * quantity * 30
            elif action == "modify":
                old_cost = unit_cost * quantity * 30
                new_sku = change.get("new_sku")
                new_unit_cost = await self._get_resource_unit_cost(resource_type, new_sku)
                monthly_impact = (new_unit_cost - unit_cost) * quantity * 30
            else:
                monthly_impact = 0.0

            impact_analysis["changes"].append(
                {
                    "resource_type": resource_type,
                    "action": action,
                    "monthly_impact": monthly_impact,
                    "annual_impact": monthly_impact * 12,
                }
            )

            impact_analysis["total_impact"] += monthly_impact

        impact_analysis["predicted_monthly_cost"] = (
            impact_analysis["current_monthly_cost"] + impact_analysis["total_impact"]
        )
        impact_analysis["percentage_change"] = (
            (impact_analysis["total_impact"] / impact_analysis["current_monthly_cost"]) * 100
            if impact_analysis["current_monthly_cost"] > 0
            else 0
        )

        return impact_analysis

    def _fit_trend_model(self, X: np.ndarray, y: np.ndarray) -> tuple[Any, float]:
        model = LinearRegression()
        model.fit(X, y)

        predictions = model.predict(X)
        r2_score = model.score(X, y)

        return model, r2_score

    def _fit_seasonal_model(self, X: np.ndarray, y: np.ndarray) -> tuple[Any, float]:
        poly_features = PolynomialFeatures(degree=3)
        X_poly = poly_features.fit_transform(X)

        model = LinearRegression()
        model.fit(X_poly, y)

        predictions = model.predict(X_poly)
        r2_score = model.score(X_poly, y)

        wrapped_model = SeasonalModelWrapper(model, poly_features)

        return wrapped_model, r2_score

    def _detect_seasonality(self, y: np.ndarray) -> bool:
        if len(y) < 14:
            return False

        weekly_pattern = []
        for i in range(7):
            daily_values = y[i::7]
            if len(daily_values) > 1:
                weekly_pattern.append(np.mean(daily_values))

        if len(weekly_pattern) >= 7:
            pattern_variance = np.var(weekly_pattern)
            total_variance = np.var(y)

            return pattern_variance / total_variance > 0.1 if total_variance > 0 else False

        return False

    def _determine_trend(self, predictions: np.ndarray) -> str:
        if len(predictions) < 2:
            return "stable"

        first_week = np.mean(predictions[:7]) if len(predictions) >= 7 else predictions[0]
        last_week = np.mean(predictions[-7:]) if len(predictions) >= 7 else predictions[-1]

        change_percentage = ((last_week - first_week) / first_week) * 100 if first_week > 0 else 0

        if change_percentage > 5:
            return "increasing"
        elif change_percentage < -5:
            return "decreasing"
        else:
            return "stable"

    async def _detect_anomalies(
        self,
        historical_data: list[dict[str, Any]],
        model: Any,
        X: np.ndarray,
    ) -> list[dict[str, Any]]:
        if not historical_data:
            return []

        predictions = model.predict(X)
        anomalies = []

        for i, (data_point, prediction) in enumerate(
            zip(historical_data, predictions, strict=False)
        ):
            actual = data_point["cost"]
            deviation = abs(actual - prediction) / prediction if prediction > 0 else 0

            if deviation > 0.3:
                anomalies.append(
                    {
                        "date": data_point["date"].isoformat(),
                        "actual_cost": actual,
                        "expected_cost": float(prediction),
                        "deviation_percentage": deviation * 100,
                        "severity": "high" if deviation > 0.5 else "medium",
                    }
                )

        return anomalies

    def _classify_severity(self, z_score: float) -> str:
        if z_score > 4:
            return "critical"
        elif z_score > 3:
            return "high"
        elif z_score > 2:
            return "medium"
        else:
            return "low"

    async def _identify_probable_cause(
        self,
        subscription_id: str,
        date: datetime,
        deviation: float,
    ) -> str:
        if deviation > 50:
            return "Major resource deployment or scaling event"
        elif deviation > 20:
            return "Increased usage or new service activation"
        elif deviation < -20:
            return "Resource decommissioning or optimization applied"
        else:
            return "Normal variation or minor configuration change"

    async def _get_historical_data(
        self,
        subscription_id: str,
        days: int,
    ) -> list[dict[str, Any]]:
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        scope = f"/subscriptions/{subscription_id}"
        usage_data = await self.cost_ingestion.get_usage_details(
            scope,
            start_date,
            end_date,
            granularity="Daily",
        )

        daily_costs = {}
        for item in usage_data:
            date_str = item.get("UsageDate", item.get("Date", ""))
            if date_str:
                date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                date_key = date.date()
                cost = float(item.get("Cost", 0))

                if date_key not in daily_costs:
                    daily_costs[date_key] = 0
                daily_costs[date_key] += cost

        return [
            {"date": datetime.combine(date, datetime.min.time()), "cost": cost}
            for date, cost in sorted(daily_costs.items())
        ]

    async def _get_current_month_cost(self, subscription_id: str) -> float:
        now = datetime.utcnow()
        start_date = now.replace(day=1)

        scope = f"/subscriptions/{subscription_id}"
        usage_data = await self.cost_ingestion.get_usage_details(
            scope,
            start_date,
            now,
            granularity="None",
        )

        total_cost = sum(float(item.get("Cost", 0)) for item in usage_data)
        return total_cost

    async def _get_current_costs_by_resource_type(
        self,
        subscription_id: str,
    ) -> dict[str, float]:
        now = datetime.utcnow()
        start_date = now.replace(day=1)

        scope = f"/subscriptions/{subscription_id}"
        usage_data = await self.cost_ingestion.get_usage_details(
            scope,
            start_date,
            now,
            granularity="None",
            group_by=["ResourceType"],
        )

        costs_by_type = {}
        for item in usage_data:
            resource_type = item.get("ResourceType", "Unknown")
            cost = float(item.get("Cost", 0))

            if resource_type not in costs_by_type:
                costs_by_type[resource_type] = 0
            costs_by_type[resource_type] += cost

        return costs_by_type

    async def _identify_reduction_strategies(
        self,
        subscription_id: str,
        target_percentage: float,
    ) -> list[dict[str, Any]]:
        from app.tools.finops.optimization import OptimizationService, OptimizationStrategy

        optimizer = OptimizationService()

        if target_percentage > 20:
            strategy = OptimizationStrategy.AGGRESSIVE
        elif target_percentage > 10:
            strategy = OptimizationStrategy.BALANCED
        else:
            strategy = OptimizationStrategy.CONSERVATIVE

        recommendations = await optimizer.analyze_optimization_opportunities(
            subscription_id, strategy, min_savings_threshold=0
        )

        strategies = []
        cumulative_savings = 0.0
        current_monthly_cost = await self._get_current_month_cost(subscription_id)
        target_savings = current_monthly_cost * (target_percentage / 100)

        for rec in recommendations:
            if cumulative_savings >= target_savings:
                break

            strategies.append(
                {
                    "action": rec.recommendation_type,
                    "resource": rec.resource_id,
                    "estimated_savings": rec.estimated_monthly_savings,
                    "implementation_effort": rec.implementation_effort,
                    "risk_level": rec.risk_level,
                }
            )
            cumulative_savings += rec.estimated_monthly_savings

        return strategies

    async def _get_resource_unit_cost(
        self,
        resource_type: str,
        sku: str | None,
    ) -> float:
        cost_mapping = {
            "Microsoft.Compute/virtualMachines": {
                "Standard_B1s": 0.42,
                "Standard_B2s": 1.68,
                "Standard_D2s_v3": 3.36,
                "Standard_D4s_v3": 6.72,
                "Standard_D8s_v3": 13.44,
                "Standard_E2s_v3": 4.20,
                "Standard_E4s_v3": 8.40,
                "default": 5.00,
            },
            "Microsoft.Storage/storageAccounts": {
                "Standard_LRS": 0.0208,
                "Standard_GRS": 0.0458,
                "Standard_ZRS": 0.026,
                "Standard_GZRS": 0.0573,
                "Premium_LRS": 0.15,
                "default": 0.025,
            },
            "Microsoft.Sql/servers/databases": {
                "Basic": 4.99,
                "S0": 15.00,
                "S1": 30.00,
                "S2": 75.00,
                "P1": 465.00,
                "P2": 930.00,
                "default": 50.00,
            },
            "Microsoft.ContainerService/managedClusters": {
                "Standard_D2s_v3": 3.36,
                "Standard_D4s_v3": 6.72,
                "Standard_D8s_v3": 13.44,
                "default": 10.00,
            },
        }

        resource_costs = cost_mapping.get(resource_type, {})
        if sku and sku in resource_costs:
            return resource_costs[sku]
        return resource_costs.get("default", 10.0)

    def _create_default_forecast(self, forecast_days: int) -> CostForecast:
        return CostForecast(
            period_start=datetime.utcnow(),
            period_end=datetime.utcnow() + timedelta(days=forecast_days),
            predicted_cost=0.0,
            confidence_interval=(0.0, 0.0),
            confidence_level=0.95,
            trend="insufficient_data",
            seasonality_detected=False,
            anomalies=[],
            model_accuracy=0.0,
        )


class SeasonalModelWrapper:
    def __init__(self, model: LinearRegression, poly_features: PolynomialFeatures):
        self.model = model
        self.poly_features = poly_features

    def predict(self, X: np.ndarray) -> np.ndarray:
        X_poly = self.poly_features.transform(X)
        return self.model.predict(X_poly)
