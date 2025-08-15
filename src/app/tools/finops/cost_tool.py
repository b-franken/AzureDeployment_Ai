from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.tools.base import Tool, ToolResult

from .analyzer import CostAnalyzer, CostManagementSystem, CostOptimizationStrategy


class AzureCosts(Tool):
    name = "azure_costs"
    description = "Analyze Azure resource costs, detect anomalies, create budgets, and suggest optimizations."
    schema = {
        "type": "object",
        "properties": {
            "subscription_id": {"type": "string"},
            "action": {
                "type": "string",
                "enum": ["analyze", "budget_status", "optimize", "report"],
            },
            "resource": {"type": "object"},
            "level": {
                "type": "string",
                "enum": ["aggressive", "balanced, conservative"],
            },
            "format": {"type": "string", "enum": ["json", "csv"]},
        },
        "required": ["action"],
        "additionalProperties": True,
    }

    def __init__(self) -> None:
        self.analyzer = CostAnalyzer()
        self.cms = CostManagementSystem()

    async def run(self, **kwargs: Any) -> ToolResult:
        act = (kwargs.get("action") or "").lower()
        if act == "analyze":
            res = kwargs.get("resource") or {}
            start_date = self._parse_date(
                kwargs.get("start_date")
            ) or datetime.utcnow() - timedelta(days=30)
            end_date = self._parse_date(kwargs.get("end_date")) or datetime.utcnow()
            items = await self.analyzer.analyze([res], start_date, end_date)
            cost = items[0] if items else None
            if not cost:
                return {"ok": False, "summary": "no cost computed", "output": ""}
            return {
                "ok": True,
                "summary": f"analyzed {cost.resource_name}",
                "output": cost.__dict__,
            }

        if act == "budget_status":
            bid = kwargs.get("budget_id") or ""
            amount = kwargs.get("amount")
            period = kwargs.get("period")
            if amount is not None and period:
                out = await self.cms.budget_manager.set_budget(
                    kwargs.get("subscription_id", ""), float(amount), str(period)
                )
                return {
                    "ok": True,
                    "summary": f"budget set {out.get('budget_id', '')}",
                    "output": out,
                }
            out = {"budget_id": bid, "status": "unknown", "amount": 0.0}
            return {"ok": True, "summary": f"budget {bid} status", "output": out}

        if act == "optimize":
            level_str = (kwargs.get("level") or "balanced").lower()
            lvl = self._map_level(level_str)
            min_savings = float(kwargs.get("min_savings", 50.0))
            recs = await self.cms.get_optimization_recommendations(
                kwargs.get("subscription_id", ""), lvl, min_savings
            )
            return {
                "ok": True,
                "summary": f"{len(recs)} recs",
                "output": [r.__dict__ for r in recs],
            }

        if act == "report":
            fmt = (kwargs.get("format") or "json").lower()
            insights = await self.cms.get_cost_insights(
                kwargs.get("subscription_id", "")
            )
            if fmt == "csv":
                text = self._insights_to_csv(insights)
                return {"ok": True, "summary": "report csv", "output": text}
            return {"ok": True, "summary": "report json", "output": insights}

        return {"ok": False, "summary": "unknown action", "output": ""}

    def _map_level(self, level: str) -> CostOptimizationStrategy:
        if level == "aggressive":
            return CostOptimizationStrategy.AGGRESSIVE
        if level == "conservative":
            return CostOptimizationStrategy.CONSERVATIVE
        return CostOptimizationStrategy.BALANCED

    def _parse_date(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    def _insights_to_csv(self, insights: dict[str, Any]) -> str:
        lines: list[str] = []
        for k, v in insights.items():
            if isinstance(v, dict):
                for kk, vv in v.items():
                    lines.append(f"{k}.{kk},{self._to_scalar(vv)}")
            elif isinstance(v, list):
                lines.append(f"{k},{self._to_scalar(v)}")
            else:
                lines.append(f"{k},{self._to_scalar(v)}")
        return "\n".join(["key,value", *lines])

    def _to_scalar(self, v: Any) -> str:
        if isinstance(v, int | float | str):
            return str(v)
        return str(v)
