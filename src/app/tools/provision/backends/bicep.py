from __future__ import annotations

from typing import Any


class BicepBackend:
    async def plan(self, spec: dict[str, Any]) -> tuple[bool, str]:
        product = spec.get("product")
        if product not in ["storage_account", "web_app"]:
            return False, f"Bicep backend does not support product: {product}"

        p = spec.get("parameters", {})
        rg = p.get("resource_group", "undefined")
        loc = p.get("location", "undefined")
        name = p.get("name", "undefined")

        if product == "storage_account":
            plan = f"Deploy storage account '{name}' in location '{loc}' to resource group '{rg}'"
        else:
            plan = f"Deploy {product} '{name}' in location '{loc}' to resource group '{rg}'"

        return True, plan

    async def apply(self, spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        return False, {"message": "Bicep backend apply not implemented"}
