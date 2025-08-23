from __future__ import annotations

from typing import Any

from .types import Anomaly, RootCause


class RootCauseAnalyzer:
    async def analyze(
        self,
        anomaly: Anomaly,
        metrics: dict[str, Any],
        logs: list[str],
        traces: list[dict[str, Any]],
    ) -> RootCause:
        name = anomaly.metric.lower()
        evidence: list[str] = []
        if "cpu" in name:
            cause = "resource_pressure_cpu"
            evidence.append("cpu")
        elif "memory" in name or "rss" in name:
            cause = "resource_pressure_memory"
            evidence.append("memory")
        elif "latency" in name or "duration" in name:
            cause = "downstream_latency"
            evidence.append("latency")
        elif "error" in name or any("error" in s.lower() for s in logs[-100:]):
            cause = "error_spike"
            evidence.append("errors")
        else:
            cause = "unknown"
        conf = 0.6 if cause != "unknown" else 0.3
        return RootCause(cause=cause, confidence=conf, evidence=evidence)
