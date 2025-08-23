from __future__ import annotations

from datetime import datetime
from statistics import fmean, pstdev
from typing import Any

from .types import Anomaly


class AnomalyDetector:
    async def detect(
        self,
        metrics: dict[str, list[tuple[datetime, float]] | list[float]],
        logs: list[str],
        traces: list[dict[str, Any]],
    ) -> list[Anomaly]:
        out: list[Anomaly] = []
        for name, series in metrics.items():
            values: list[float]
            ts: datetime
            if series and isinstance(series[0], tuple):
                ts, last = series[-1]  # type: ignore[assignment]
                values = [float(v) for _, v in series]  # type: ignore[misc]
            else:
                arr = [float(x) for x in series] if series else []
                values = arr
                ts = datetime.utcnow()
                last = arr[-1] if arr else 0.0
            if len(values) < 5:
                continue
            mean = fmean(values)
            sd = pstdev(values) or 1.0
            z = abs((last - mean) / sd)
            if z < 3.0:
                continue
            sev = "low" if z < 4 else "medium" if z < 6 else "high" if z < 8 else "critical"
            out.append(
                Anomaly(
                    metric=name,
                    value=float(last),
                    severity=sev,
                    ts=ts,
                    score=float(z),
                    tags={},
                )
            )
        if any("timeout" in s.lower() or "error" in s.lower() for s in logs[-200:]):
            out.append(
                Anomaly(
                    metric="logs.error_rate",
                    value=1.0,
                    severity="medium",
                    ts=datetime.utcnow(),
                    score=3.5,
                    tags={"source": "logs"},
                )
            )
        return out
