from __future__ import annotations

import logging
from typing import Any, TypedDict, cast

from app.common.async_pool import bounded_gather

from .base import ApplyResult, Backend, PlanResult

logger = logging.getLogger(__name__)


class ActionArgs(TypedDict, total=False):
    resource_group: str
    location: str
    tags: dict[str, str]
    name: str
    sku: str
    linux: bool
    runtime: str | None
    plan: str
    access_tier: str
    dry_run: bool
    force: bool
    dns_prefix: str
    node_count: int
    admin_user_enabled: bool
    capacity: int
    publisher_email: str
    publisher_name: str
    tier: str
    auto_inflate: bool
    max_throughput: int


class Action(TypedDict):
    action: str
    args: ActionArgs


class SdkBackend(Backend):
    def __init__(self) -> None:
        self.azure = None
        self._ensure_azure_tool()
        self._concurrency = 8

    def _ensure_azure_tool(self) -> None:
        if self.azure is None:
            try:
                from app.tools.azure.tool import AzureProvision

                self.azure = AzureProvision()
            except Exception as e:
                logger.warning(
                    "Failed to import AzureProvision; proceeding without Azure SDK. %s", e
                )
                self.azure = None

    def _tags(self, spec: dict[str, Any]) -> dict[str, str]:
        p = spec.get("parameters", {})
        env = spec.get("env", "dev")
        tags = dict(p.get("tags") or {})
        tags.setdefault("env", env)
        return tags

    def _build_actions(self, spec: dict[str, Any]) -> list[Action]:
        p = spec["parameters"]
        product = spec["product"]
        tags = self._tags(spec)

        if product == "web_app":
            plan_cfg = p["plan"]
            runtime = p.get("runtime")
            return [
                {
                    "action": "create_rg",
                    "args": {
                        "resource_group": p["resource_group"],
                        "location": p["location"],
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
                {
                    "action": "create_plan",
                    "args": {
                        "resource_group": p["resource_group"],
                        "name": plan_cfg["name"],
                        "location": p["location"],
                        "sku": plan_cfg["sku"],
                        "linux": bool(plan_cfg.get("linux", True)),
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
                {
                    "action": "create_webapp",
                    "args": {
                        "resource_group": p["resource_group"],
                        "name": p["name"],
                        "plan": plan_cfg["name"],
                        "runtime": runtime,
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
            ]

        if product == "storage_account":
            sku = p.get("sku", "Standard_LRS")
            if sku in {"Basic", "Standard", "Premium"}:
                sku = "Standard_LRS"
            return [
                {
                    "action": "create_rg",
                    "args": {
                        "resource_group": p["resource_group"],
                        "location": p["location"],
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
                {
                    "action": "create_storage",
                    "args": {
                        "resource_group": p["resource_group"],
                        "location": p["location"],
                        "name": p["name"],
                        "sku": sku,
                        "access_tier": p.get("access_tier", "Hot"),
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
            ]

        if product == "aks_cluster":
            return [
                {
                    "action": "create_rg",
                    "args": {
                        "resource_group": p["resource_group"],
                        "location": p["location"],
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
                {
                    "action": "create_aks",
                    "args": {
                        "resource_group": p["resource_group"],
                        "location": p["location"],
                        "name": p["name"],
                        "dns_prefix": p["dns_prefix"],
                        "node_count": int(p.get("node_count", 2)),
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
            ]

        if product == "container_registry":
            return [
                {
                    "action": "create_rg",
                    "args": {
                        "resource_group": p["resource_group"],
                        "location": p["location"],
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
                {
                    "action": "create_acr",
                    "args": {
                        "resource_group": p["resource_group"],
                        "location": p["location"],
                        "name": p["name"],
                        "sku": p.get("sku", "Basic"),
                        "admin_user_enabled": bool(p.get("admin_user_enabled", True)),
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
            ]

        if product == "api_management":
            return [
                {
                    "action": "create_rg",
                    "args": {
                        "resource_group": p["resource_group"],
                        "location": p["location"],
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
                {
                    "action": "create_apim",
                    "args": {
                        "resource_group": p["resource_group"],
                        "location": p["location"],
                        "name": p["name"],
                        "sku": p.get("sku_name", "Developer"),
                        "capacity": int(p.get("capacity", 1)),
                        "publisher_email": p.get("publisher_email", "admin@contoso.com"),
                        "publisher_name": p.get("publisher_name", "Contoso"),
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
            ]

        if product == "event_hub":
            return [
                {
                    "action": "create_rg",
                    "args": {
                        "resource_group": p["resource_group"],
                        "location": p["location"],
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
                {
                    "action": "create_eventhub",
                    "args": {
                        "resource_group": p["resource_group"],
                        "location": p["location"],
                        "name": p["name"],
                        "tier": p.get("tier", "Standard"),
                        "capacity": int(p.get("capacity", 1)),
                        "auto_inflate": bool(p.get("auto_inflate", True)),
                        "max_throughput": int(p.get("max_throughput", 10)),
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
            ]

        return []

    def _build_stages(self, spec: dict[str, Any]) -> list[list[Action]]:
        seq = self._build_actions(spec)
        if not seq:
            return []
        product = spec.get("product")
        if product == "web_app":
            if (
                len(seq) == 3
                and seq[0]["action"] == "create_rg"
                and seq[1]["action"] == "create_plan"
                and seq[2]["action"] == "create_webapp"
            ):
                return [[seq[0]], [seq[1]], [seq[2]]]
        first, rest = seq[0], seq[1:]
        if first["action"] == "create_rg":
            if not rest:
                return [[first]]
            return [[first], rest]
        return [seq]

    async def plan(self, spec: dict[str, Any]) -> PlanResult:
        try:
            actions = self._build_actions(spec)
            if not actions:
                return False, f"No actions defined for product: {spec.get('product')}"
            return True, self._summarize_plan("SDK plan", actions)
        except Exception as e:
            return False, str(e)

    async def apply(self, spec: dict[str, Any]) -> ApplyResult:
        if self.azure is None:
            return False, {"message": "Azure SDK not initialized"}
        stages = self._build_stages(spec)
        if not stages:
            return False, {"message": f"No actions defined for product: {spec.get('product')}"}
        results: dict[str, Any] = {"steps": []}
        for stage in stages:

            async def _run_one(a: Action) -> dict[str, Any]:
                try:
                    return await self.azure.run(action=a["action"], **a["args"])
                except Exception as e:
                    return {"ok": False, "summary": "exception", "output": str(e)}

            stage_res = await bounded_gather(*[_run_one(a) for a in stage], limit=self._concurrency)
            for a, res in zip(stage, stage_res, strict=False):
                ok = bool(res.get("ok"))
                results["steps"].append(
                    {
                        "action": a["action"],
                        "ok": ok,
                        "summary": res.get("summary"),
                        "output": res.get("output"),
                    }
                )
            if not all(bool(r.get("ok")) for r in stage_res):
                return False, results
        return True, results

    def _summarize_plan(self, title: str, items: list[Action]) -> str:
        lines = [title, ""]
        for i, it in enumerate(items, 1):
            action = it.get("action", "unknown")
            args = it.get("args", {})
            key_params = []
            if "resource_group" in args:
                key_params.append(f"rg={args['resource_group']}")
            if "name" in args:
                key_params.append(f"name={cast(dict[str, Any], args)['name']}")
            if "location" in args:
                key_params.append(f"location={args['location']}")
            lines.append(f"{i}. {action} ({', '.join(key_params)})")
        return "\n".join(lines)
