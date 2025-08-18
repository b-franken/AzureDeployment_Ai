from __future__ import annotations

import json
from typing import Any, TypedDict, cast

from mcp.server.fastmcp import Context

from app.mcp.server import MCPServer
from app.tools.azure.clients import get_clients
from app.tools.provision.orchestrator import ProvisionOrchestrator


class PlanPreviewArgs(TypedDict, total=False):
    request: str
    env: str
    subscription_id: str
    resource_group: str
    location: str
    include_cost_estimate: bool


def register_extensions(server: MCPServer) -> None:
    mcp = server.mcp

    @mcp.tool(
        name="plan_preview",
        description=(
            "Create a safe plan from plain English. Returns AVM Bicep, What-If preview, "
            "and optional cost estimate. Does not apply changes."
        ),
    )
    async def plan_preview(args: PlanPreviewArgs, context: Context) -> dict[str, Any]:
        req = cast(dict[str, Any], dict(args or {}))
        orch = ProvisionOrchestrator()
        res = await orch.run(
            request=req.get("request"),
            backend="avm",
            env=str(req.get("env") or "dev"),
            plan_only=True,
            subscription_id=req.get("subscription_id"),
            resource_group=req.get("resource_group"),
            location=req.get("location"),
            include_cost_estimate=bool(req.get("include_cost_estimate", True)),
        )

        if isinstance(res.get("output"), str):
            try:
                res["output"] = json.loads(res["output"])
            except Exception:
                pass
        return cast(dict[str, Any], res)

    @mcp.resource("azure://quotas/{subscription_id}/{location}")
    async def quotas(context: Context, subscription_id: str, location: str) -> dict[str, Any]:
        clients = await get_clients(subscription_id)
        usages = await clients.run(clients.cmp.usage.list, location)
        items: list[dict[str, Any]] = []
        for u in usages:
            key = getattr(getattr(u, "name", None), "value", None) or "unknown"
            current = int(getattr(u, "current_value", 0))
            limit = int(getattr(u, "limit", 0))
            items.append(
                {
                    "name": key,
                    "current": current,
                    "limit": limit,
                    "available": max(limit - current, 0),
                }
            )
        return {"region": location, "items": items}

    @mcp.prompt("explain_plan")
    async def explain_plan_prompt(
        context: Context,
        plan_json: str,
        audience: str = "engineering team",
    ) -> str:
        try:
            obj = json.loads(plan_json)
        except Exception:
            obj = {"raw": plan_json}
        title = f"Plan preview for {audience}"
        bullets = [
            "What will be created or changed",
            "Dependencies and sequencing",
            "Quota or naming risks",
            "Estimated monthly cost if provided",
            "Rollback posture and safe retry if apply fails",
        ]
        return f"""{title}

Key points to cover:
- {bullets[0]}
- {bullets[1]}
- {bullets[2]}
- {bullets[3]}
- {bullets[4]}

Raw plan object:
{json.dumps(obj, indent=2)}
"""
