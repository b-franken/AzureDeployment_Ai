from __future__ import annotations

from typing import Any

from .types import Anomaly, Prediction


class IncidentPredictor:
    async def predict(
        self,
        metrics: dict[str, Any],
        anomalies: list[Anomaly],
        lookback_hours: int = 24,
    ) -> list[Prediction]:
        n = len(anomalies)
        p = min(0.95, 0.1 + 0.15 * n)
        bucket = (
            "capacity_incident"
            if any(a.metric.startswith("cpu") or a.metric.startswith("memory") for a in anomalies)
            else "reliability_incident"
        )
        return [
            Prediction(issue=bucket, probability=float(round(p, 2)), horizon_hours=lookback_hours)
        ]
