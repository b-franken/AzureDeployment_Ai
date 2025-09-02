from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta
from statistics import NormalDist
from typing import Any, Protocol, TypedDict

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures

from app.tools.finops.cost_ingestion import CostIngestionService

# Constants for magic values
MINIMUM_HISTORICAL_DATA_POINTS = 7
MINIMUM_FORECAST_PERIOD_DAYS = 14
DEFAULT_CONFIDENCE_LEVEL = 0.95
OPTIMAL_SAMPLE_SIZE = 30
ANOMALY_THRESHOLD_MULTIPLIER = 2.0
SEASONALITY_DETECTION_POINTS = 21
OUTLIER_DETECTION_FACTOR = 1.5
MODEL_ACCURACY_THRESHOLD = 0.8
SEASONALITY_MIN_PERIOD = 14
SEASONALITY_PATTERN_VARIANCE_THRESHOLD = 0.1
TREND_MIN_PERIODS = 2
TREND_CHANGE_THRESHOLD = 5.0
ANOMALY_DEVIATION_THRESHOLD = 0.3
HIGH_SEVERITY_DEVIATION_THRESHOLD = 0.5
CRITICAL_Z_SCORE_THRESHOLD = 4.0
HIGH_Z_SCORE_THRESHOLD = 3.0
MEDIUM_Z_SCORE_THRESHOLD = 2.0
MAJOR_DEVIATION_THRESHOLD = 50.0
MODERATE_DEVIATION_THRESHOLD = 20.0
AGGRESSIVE_OPTIMIZATION_THRESHOLD = 20.0
BALANCED_OPTIMIZATION_THRESHOLD = 10.0


def _z_score(confidence_level: float) -> float:
    return float(NormalDist().inv_cdf((1.0 + confidence_level) / 2.0))


class ForecastModel(Protocol):
    """Protocol for forecasting models."""

    def predict(self, X: NDArray[np.floating]) -> NDArray[np.floating]:
        """Predict values based on input features."""
        ...


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
    index: int
    timestamp: datetime
    actual_value: float
    expected_value: float
    deviation_percentage: float
    severity: str
    probable_cause: str


class ImpactChange(TypedDict):
    resource_type: str
    action: str
    old_monthly_cost: float
    new_monthly_cost: float
    monthly_impact: float
    annual_impact: float


class ImpactAnalysisDraft(TypedDict, total=False):
    current_monthly_cost: float
    changes: list[ImpactChange]
    total_impact: float
    predicted_monthly_cost: float
    percentage_change: float


class ImpactAnalysisDict(TypedDict):
    current_monthly_cost: float
    changes: list[ImpactChange]
    total_impact: float
    predicted_monthly_cost: float
    percentage_change: float


class ForecastingService:
    def __init__(self) -> None:
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

        X = np.array([(d - dates[0]).days for d in dates], dtype=float).reshape(-1, 1)
        y = np.array(costs, dtype=float)

        if include_seasonality:
            model, accuracy = self._fit_seasonal_model(X, y)
            seasonality = self._detect_seasonality(y)
        else:
            model, accuracy = self._fit_trend_model(X, y)
            seasonality = False

        future_X = np.arange(len(dates), len(dates) + forecast_days, dtype=float).reshape(-1, 1)
        predictions = model.predict(future_X)
        residuals = y - model.predict(X)
        std_error = float(np.std(residuals, ddof=1)) if residuals.size > 1 else 0.0
        margin = _z_score(confidence_level) * std_error * float(np.sqrt(forecast_days))

        total_predicted = float(np.sum(predictions))
        lower_bound = float(total_predicted - margin)
        upper_bound = float(total_predicted + margin)

        trend = self._determine_trend(predictions)
        anomalies = await self._detect_anomalies(historical_data, model, X)

        now = datetime.utcnow()
        return CostForecast(
            period_start=now,
            period_end=now + timedelta(days=forecast_days),
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
        if len(historical_data) < MINIMUM_HISTORICAL_DATA_POINTS:
            return []

        dates = [d["date"] for d in historical_data]
        costs = [d["cost"] for d in historical_data]

        X = np.array([(d - dates[0]).days for d in dates], dtype=float).reshape(-1, 1)
        y = np.array(costs, dtype=float)

        model, _ = self._fit_trend_model(X, y)
        predictions = model.predict(X)

        residuals = y - predictions
        std_residual = float(np.std(residuals, ddof=1)) if residuals.size > 1 else 0.0
        mean_residual = float(np.mean(residuals)) if residuals.size > 0 else 0.0
        if std_residual == 0.0:
            return []

        anomalies: list[AnomalyDetection] = []
        for idx, (ts, actual, expected) in enumerate(zip(dates, costs, predictions, strict=False)):
            z = abs((float(actual) - float(expected) - mean_residual) / std_residual)
            if z > sensitivity:
                deviation = (
                    ((float(actual) - float(expected)) / float(expected)) * 100.0
                    if expected != 0
                    else 0.0
                )
                anomalies.append(
                    AnomalyDetection(
                        index=idx,
                        timestamp=ts,
                        actual_value=float(actual),
                        expected_value=float(expected),
                        deviation_percentage=float(deviation),
                        severity=self._classify_severity(z),
                        probable_cause=await self._identify_probable_cause(
                            subscription_id, ts, deviation
                        ),
                    )
                )

        return anomalies

    async def generate_budget_recommendations(
        self,
        subscription_id: str,
        target_reduction_percentage: float = 10.0,
    ) -> dict[str, Any]:
        current_month_cost = await self._get_current_month_cost(subscription_id)
        forecast = await self.forecast_costs(subscription_id, forecast_days=30)
        target_budget = current_month_cost * (1 - target_reduction_percentage / 100.0)

        recommendations: dict[str, Any] = {
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
    ) -> ImpactAnalysisDict:
        current_costs = await self._get_current_costs_by_resource_type(subscription_id)

        draft: ImpactAnalysisDraft = {
            "current_monthly_cost": float(sum(current_costs.values())),
            "changes": [],
            "total_impact": 0.0,
        }

        for change in resource_changes:
            resource_type = str(change["resource_type"])
            action = str(change["action"])
            quantity = int(change.get("quantity", 1))
            unit_cost = await self._get_resource_unit_cost(resource_type, change.get("sku"))

            if action == "add":
                monthly_impact = unit_cost * quantity * 30.0
                old_cost = 0.0
                new_cost = monthly_impact
            elif action == "remove":
                monthly_impact = -unit_cost * quantity * 30.0
                old_cost = -monthly_impact
                new_cost = 0.0
            elif action == "modify":
                old_cost = unit_cost * quantity * 30.0
                new_sku = change.get("new_sku")
                new_unit_cost = await self._get_resource_unit_cost(resource_type, new_sku)
                new_cost = new_unit_cost * quantity * 30.0
                monthly_impact = new_cost - old_cost
            else:
                monthly_impact = 0.0
                old_cost = 0.0
                new_cost = 0.0

            draft["changes"].append(
                ImpactChange(
                    resource_type=resource_type,
                    action=action,
                    old_monthly_cost=float(old_cost),
                    new_monthly_cost=float(new_cost),
                    monthly_impact=float(monthly_impact),
                    annual_impact=float(monthly_impact * 12.0),
                )
            )
            draft["total_impact"] = float(draft["total_impact"]) + float(monthly_impact)

        current_monthly_cost = float(draft["current_monthly_cost"])
        total_impact = float(draft["total_impact"])
        predicted_monthly_cost = current_monthly_cost + total_impact
        percentage_change = (
            (total_impact / current_monthly_cost) * 100.0 if current_monthly_cost > 0.0 else 0.0
        )

        result: ImpactAnalysisDict = {
            "current_monthly_cost": current_monthly_cost,
            "changes": draft["changes"],
            "total_impact": total_impact,
            "predicted_monthly_cost": predicted_monthly_cost,
            "percentage_change": percentage_change,
        }
        return result

    def _fit_trend_model(
        self, X: NDArray[np.floating], y: NDArray[np.floating]
    ) -> tuple[ForecastModel, float]:
        model = LinearRegression()
        model.fit(X, y)
        r2_score = float(model.score(X, y))
        return model, r2_score

    def _fit_seasonal_model(
        self, X: NDArray[np.floating], y: NDArray[np.floating]
    ) -> tuple[ForecastModel, float]:
        poly_features = PolynomialFeatures(degree=3)
        X_poly = poly_features.fit_transform(X)
        model = LinearRegression()
        model.fit(X_poly, y)
        r2_score = float(model.score(X_poly, y))
        wrapped_model = SeasonalModelWrapper(model, poly_features)
        return wrapped_model, r2_score

    def _detect_seasonality(self, y: NDArray[np.floating]) -> bool:
        if len(y) < SEASONALITY_MIN_PERIOD:
            return False
        weekly_pattern: list[float] = []
        for i in range(7):
            daily_values = y[i::7]
            if len(daily_values) > 1:
                weekly_pattern.append(float(np.mean(daily_values)))
        if len(weekly_pattern) >= MINIMUM_HISTORICAL_DATA_POINTS:
            pattern_variance = float(np.var(weekly_pattern, ddof=0))
            total_variance = float(np.var(y, ddof=0))
            return (
                pattern_variance / total_variance > SEASONALITY_PATTERN_VARIANCE_THRESHOLD
                if total_variance > 0.0
                else False
            )
        return False

    def _determine_trend(self, predictions: NDArray[np.floating]) -> str:
        if len(predictions) < TREND_MIN_PERIODS:
            return "stable"
        first_week = (
            float(np.mean(predictions[:MINIMUM_HISTORICAL_DATA_POINTS]))
            if len(predictions) >= MINIMUM_HISTORICAL_DATA_POINTS
            else float(predictions[0])
        )
        last_week = (
            float(np.mean(predictions[-MINIMUM_HISTORICAL_DATA_POINTS:]))
            if len(predictions) >= MINIMUM_HISTORICAL_DATA_POINTS
            else float(predictions[-1])
        )
        change_percentage = (
            ((last_week - first_week) / first_week) * 100.0 if first_week > 0.0 else 0.0
        )
        if change_percentage > TREND_CHANGE_THRESHOLD:
            return "increasing"
        if change_percentage < -TREND_CHANGE_THRESHOLD:
            return "decreasing"
        return "stable"

    async def _detect_anomalies(
        self,
        historical_data: list[dict[str, Any]],
        model: Any,
        X: NDArray[np.floating],
    ) -> list[dict[str, Any]]:
        if not historical_data:
            return []
        predictions = model.predict(X)
        anomalies: list[dict[str, Any]] = []
        for idx, (data_point, prediction) in enumerate(
            zip(historical_data, predictions, strict=False)
        ):
            actual = float(data_point["cost"])
            pred_val = float(prediction)
            deviation = abs(actual - pred_val) / pred_val if pred_val > 0.0 else 0.0
            if deviation > ANOMALY_DEVIATION_THRESHOLD:
                anomalies.append(
                    {
                        "index": idx,
                        "date": data_point["date"].isoformat(),
                        "actual_cost": actual,
                        "expected_cost": pred_val,
                        "deviation_percentage": deviation * 100.0,
                        "severity": (
                            "high" if deviation > HIGH_SEVERITY_DEVIATION_THRESHOLD else "medium"
                        ),
                    }
                )
        return anomalies

    def _classify_severity(self, z_score_value: float) -> str:
        if z_score_value > CRITICAL_Z_SCORE_THRESHOLD:
            return "critical"
        if z_score_value > HIGH_Z_SCORE_THRESHOLD:
            return "high"
        if z_score_value > MEDIUM_Z_SCORE_THRESHOLD:
            return "medium"
        return "low"

    async def _identify_probable_cause(
        self,
        subscription_id: str,
        ts: datetime,
        deviation: float,
    ) -> str:
        if deviation > MAJOR_DEVIATION_THRESHOLD:
            return "Major resource deployment or scaling event"
        if deviation > MODERATE_DEVIATION_THRESHOLD:
            return "Increased usage or new service activation"
        if deviation < -MODERATE_DEVIATION_THRESHOLD:
            return "Resource decommissioning or optimization applied"
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
        daily_costs: dict[date_type, float] = {}
        for item in usage_data:
            date_str = item.get("UsageDate", item.get("Date", ""))
            if not date_str:
                continue
            dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
            dkey: date_type = dt.date()
            cost = float(item.get("Cost", 0))
            daily_costs[dkey] = daily_costs.get(dkey, 0.0) + cost
        return [
            {"date": datetime.combine(d, datetime.min.time()), "cost": cost}
            for d, cost in sorted(daily_costs.items())
        ]

    async def _get_current_month_cost(self, subscription_id: str) -> float:
        now = datetime.utcnow()
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        scope = f"/subscriptions/{subscription_id}"
        usage_data = await self.cost_ingestion.get_usage_details(
            scope,
            start_date,
            now,
            granularity="None",
        )
        return float(sum(float(item.get("Cost", 0)) for item in usage_data))

    async def _get_current_costs_by_resource_type(
        self,
        subscription_id: str,
    ) -> dict[str, float]:
        now = datetime.utcnow()
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        scope = f"/subscriptions/{subscription_id}"
        usage_data = await self.cost_ingestion.get_usage_details(
            scope,
            start_date,
            now,
            granularity="None",
            group_by=["ResourceType"],
        )
        costs_by_type: dict[str, float] = {}
        for item in usage_data:
            resource_type = str(item.get("ResourceType", "Unknown"))
            cost = float(item.get("Cost", 0))
            costs_by_type[resource_type] = costs_by_type.get(resource_type, 0.0) + cost
        return costs_by_type

    async def _identify_reduction_strategies(
        self,
        subscription_id: str,
        target_percentage: float,
    ) -> list[dict[str, Any]]:
        from app.tools.finops.optimization import OptimizationService, OptimizationStrategy

        optimizer = OptimizationService()
        if target_percentage > AGGRESSIVE_OPTIMIZATION_THRESHOLD:
            strategy = OptimizationStrategy.AGGRESSIVE
        elif target_percentage > BALANCED_OPTIMIZATION_THRESHOLD:
            strategy = OptimizationStrategy.BALANCED
        else:
            strategy = OptimizationStrategy.CONSERVATIVE
        recommendations = await optimizer.analyze_optimization_opportunities(
            subscription_id, strategy, min_savings_threshold=0
        )
        strategies: list[dict[str, Any]] = []
        cumulative_savings = 0.0
        current_monthly_cost = await self._get_current_month_cost(subscription_id)
        target_savings = current_monthly_cost * (target_percentage / 100.0)
        for rec in recommendations:
            if cumulative_savings >= target_savings:
                break
            strategies.append(
                {
                    "action": rec.recommendation_type,
                    "resource": rec.resource_id,
                    "estimated_savings": float(rec.estimated_monthly_savings),
                    "implementation_effort": rec.implementation_effort,
                    "risk_level": rec.risk_level,
                }
            )
            cumulative_savings += float(rec.estimated_monthly_savings)
        return strategies

    async def _get_resource_unit_cost(
        self,
        resource_type: str,
        sku: str | None,
    ) -> float:
        cost_mapping: dict[str, dict[str, float]] = {
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
            return float(resource_costs[sku])
        return float(resource_costs.get("default", 10.0))

    def _create_default_forecast(self, forecast_days: int) -> CostForecast:
        now = datetime.utcnow()
        return CostForecast(
            period_start=now,
            period_end=now + timedelta(days=forecast_days),
            predicted_cost=0.0,
            confidence_interval=(0.0, 0.0),
            confidence_level=0.95,
            trend="insufficient_data",
            seasonality_detected=False,
            anomalies=[],
            model_accuracy=0.0,
        )


class SeasonalModelWrapper:
    def __init__(self, model: LinearRegression, poly_features: PolynomialFeatures) -> None:
        self.model = model
        self.poly_features = poly_features

    def predict(self, X: NDArray[np.floating]) -> NDArray[np.floating]:
        X_poly = self.poly_features.transform(X)
        return self.model.predict(X_poly)
