from __future__ import annotations

from typing import Any

from app.tools.azure.clients import get_clients
from app.tools.base import Tool, ToolResult


class AzureQuotaCheck(Tool):
    """
    Check regional Compute quotas and current usage.
    """

    name = "azure_quota_check"
    description = (
        "Check Azure Compute quotas and usage for a region to catch failures before deployment."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "subscription_id": {"type": "string", "description": "Subscription ID"},
            "location": {"type": "string", "description": "Azure region, e.g. westeurope"},
            "focus": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of quota names to filter on, e.g."
                " ['cores','standardDSv5Family']",
            },
        },
        "required": ["subscription_id", "location"],
        "additionalProperties": False,
    }

    async def run(
        self,
        subscription_id: str,
        location: str,
        focus: list[str] | None = None,
    ) -> ToolResult:
        clients = await get_clients(subscription_id)
        usages = await clients.run(clients.cmp.usage.list, location)
        rows: list[dict[str, Any]] = []
        for u in usages:
            key = getattr(getattr(u, "name", None), "value", None) or "unknown"
            current = int(getattr(u, "current_value", 0))
            limit = int(getattr(u, "limit", 0))
            available = max(limit - current, 0)
            if focus and key.lower() not in {f.lower() for f in focus}:
                continue
            rows.append(
                {
                    "name": key,
                    "current": current,
                    "limit": limit,
                    "available": available,
                    "unit": getattr(u, "unit", None) or "",
                }
            )

        rows.sort(key=lambda r: (r["available"], r["limit"]), reverse=False)
        summary = (
            f"Quota check for {location}: "
            f"{sum(1 for r in rows if r['available'] <= 0)} exhausted, "
            f"{sum(1 for r in rows if 0 < r['available'] < 10)} low."
        )
        return {"ok": True, "summary": summary, "output": {"region": location, "items": rows}}
