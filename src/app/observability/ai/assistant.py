from __future__ import annotations

from typing import Any

from .detector import AnomalyDetector
from .predictor import IncidentPredictor
from .rca import RootCauseAnalyzer
from .types import HealthReport


class ObservabilityAI:
    def __init__(self) -> None:
        self.anomaly_detector = AnomalyDetector()
        self.root_cause_analyzer = RootCauseAnalyzer()
        self.incident_predictor = IncidentPredictor()

    async def analyze_system_health(
        self,
        metrics: dict[str, Any],
        logs: list[str],
        traces: list[dict[str, Any]],
    ) -> dict[str, Any]:
        anomalies = await self.anomaly_detector.detect(metrics, logs, traces)
        predictions = await self.incident_predictor.predict(metrics, anomalies, lookback_hours=24)
        root_causes: dict[str, Any] = {}
        for a in anomalies:
            rc = await self.root_cause_analyzer.analyze(a, metrics, logs, traces)
            root_causes[a.id] = rc
        report = HealthReport(
            health_score=self._calculate_health_score(anomalies, predictions),
            anomalies=anomalies,
            predictions=predictions,
            root_causes=root_causes,
            recommended_actions=self._generate_recommendations(anomalies, predictions, root_causes),
        )
        return report.model_dump()

    def _calculate_health_score(self, anomalies: list[Any], predictions: list[Any]) -> float:
        score = 100.0
        for a in anomalies:
            score -= {"low": 2.5, "medium": 7.5, "high": 15.0, "critical": 25.0}.get(
                getattr(a, "severity", "low"), 2.5
            )
        for p in predictions:
            score -= 10.0 * float(getattr(p, "probability", 0.0))
        return max(0.0, min(100.0, round(score, 1)))

    def _generate_recommendations(
        self,
        anomalies: list[Any],
        predictions: list[Any],
        root_causes: dict[str, Any],
    ) -> list[str]:
        recs: list[str] = []
        if any("cpu" in a.metric for a in anomalies):
            recs.append("verhoog cpu of schaal instances")
        if any("memory" in a.metric for a in anomalies):
            recs.append("optimaliseer memory of schaal omhoog")
        if any("latency" in a.metric for a in anomalies):
            recs.append("onderzoek downstream latency en timeouts")
        if any("error" in a.metric for a in anomalies):
            recs.append("bekijk recente fouten en rollbacks")
        if not recs:
            recs.append("monitor verder en stel alerts bij")
        return recs
