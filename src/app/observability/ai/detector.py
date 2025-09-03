from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from statistics import fmean, pstdev
from typing import Any, Literal, cast

from opentelemetry import trace

from app.core.logging import get_logger

from .types import Anomaly

logger = get_logger(__name__)
tracer = trace.get_tracer("app.observability.ai.detector")

Severity = Literal["low", "medium", "high", "critical"]


class AnomalyDetector:
    async def detect(
        self,
        metrics: dict[str, list[tuple[datetime, float]] | list[float]],
        logs: list[str],
        traces: list[dict[str, Any]],
    ) -> list[Anomaly]:
        anomalies: list[Anomaly] = []
        with tracer.start_as_current_span("observability.anomaly.detect") as span:
            span.set_attribute("metrics.count", len(metrics))
            span.set_attribute("logs.count", len(logs))
            span.set_attribute("traces.count", len(traces))
            try:
                for name, series in metrics.items():
                    try:
                        if not series:
                            continue
                        first = series[0]
                        if isinstance(first, tuple):
                            series_tuples = cast("Sequence[tuple[datetime, float]]", series)
                            ts, last = series_tuples[-1]
                            values = [float(v) for _, v in series_tuples]
                        else:
                            series_floats = cast("Sequence[float]", series)
                            if not series_floats:
                                continue
                            values = [float(x) for x in series_floats]
                            ts = datetime.utcnow()
                            last = float(values[-1])
                        if len(values) < 5:
                            continue
                        mean = fmean(values)
                        sd = pstdev(values)
                        if sd == 0.0:
                            sd = 1.0
                        z = abs((last - mean) / sd)
                        if z < 3.0:
                            continue
                        sev = self._severity_from_z(z)
                        anomaly = Anomaly(
                            metric=name,
                            value=float(last),
                            severity=sev,
                            ts=ts,
                            score=float(z),
                            tags={},
                        )
                        anomalies.append(anomaly)
                    except Exception as e:
                        logger.exception("anomaly_detection_metric_failed", extra={"metric": name})
                        span.record_exception(e)
                        span.set_attribute("error.metric", name)
                        span.set_attribute("error.type", type(e).__name__)
                        span.set_attribute("error", True)
                        continue
                if any("timeout" in s.lower() or "error" in s.lower() for s in logs[-200:]):
                    anomalies.append(
                        Anomaly(
                            metric="logs.error_rate",
                            value=1.0,
                            severity="medium",
                            ts=datetime.utcnow(),
                            score=3.5,
                            tags={"source": "logs"},
                        )
                    )
                span.set_attribute("anomalies.count", len(anomalies))
            except Exception as e:
                logger.exception("anomaly_detection_failed")
                span.record_exception(e)
                span.set_attribute("error", True)
        return anomalies

    def _severity_from_z(self, z: float) -> Severity:
        if z < 4:
            return "low"
        if z < 6:
            return "medium"
        if z < 8:
            return "high"
        return "critical"
