from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SdkBackend:
    def __init__(self) -> None:
        self.azure = None
        self._ensure_azure_tool()

    def _ensure_azure_tool(self) -> None:
        if self.azure is None:
            try:
                from app.tools.azure.tool import AzureProvision

                self.azure = AzureProvision()
            except ImportError as e:
                logger.warning(
                    "Failed to import AzureProvision; proceeding without Azure SDK. %s",
                    e,
                )
                self.azure = None

    def _build_actions(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        p = spec["parameters"]
        product = spec["product"]
        env = spec.get("env", "dev")
        tags = dict(p.get("tags") or {})
        tags.setdefault("env", env)

        actions = []

        if product == "web_app":
            actions = [
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
                        "name": p["plan"]["name"],
                        "location": p["location"],
                        "sku": p["plan"]["sku"],
                        "linux": bool(p["plan"]["linux"]),
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
                        "plan": p["plan"]["name"],
                        "runtime": p.get("runtime"),
                        "tags": tags,
                        "dry_run": False,
                        "force": False,
                    },
                },
            ]
        elif product == "storage_account":
            sku = p.get("sku", "Standard_LRS")
            if sku in ["Basic", "Standard", "Premium"]:
                sku = "Standard_LRS"

            actions = [
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

        return actions

    async def plan(self, spec: dict[str, Any]) -> tuple[bool, str]:
        try:
            actions = self._build_actions(spec)
            if not actions:
                return False, f"No actions defined for product: {spec.get('product')}"
            return True, self._summarize_plan("SDK plan", actions)
        except Exception as e:
            return False, str(e)

    async def apply(self, spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        if self.azure is None:
            return False, {"message": "Azure SDK not initialized"}

        actions = self._build_actions(spec)
        results: dict[str, Any] = {"steps": []}

        for a in actions:
            try:
                res = await self.azure.run(action=a["action"], **a["args"])
                ok = bool(res.get("ok"))
                results["steps"].append(
                    {
                        "action": a["action"],
                        "ok": ok,
                        "summary": res.get("summary"),
                        "output": res.get("output"),
                    }
                )
                if not ok:
                    return False, results
            except Exception as e:
                results["steps"].append(
                    {
                        "action": a["action"],
                        "ok": False,
                        "summary": "exception",
                        "output": str(e),
                    }
                )
                return False, results

        return True, results

    def _summarize_plan(self, title: str, items: list[dict[str, Any]]) -> str:
        lines = [title, ""]
        for i, it in enumerate(items, 1):
            action = it.get("action", "unknown")
            args = it.get("args", {})
            key_params = []
            if "resource_group" in args:
                key_params.append(f"rg={args['resource_group']}")
            if "name" in args:
                key_params.append(f"name={args['name']}")
            if "location" in args:
                key_params.append(f"location={args['location']}")
            lines.append(f"{i}. {action} ({', '.join(key_params)})")
        return "\n".join(lines)
