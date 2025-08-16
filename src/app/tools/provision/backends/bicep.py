from __future__ import annotations

from typing import Any

from .base import ApplyResult, Backend, PlanResult


class BicepBackend(Backend):
    SUPPORTED = {"storage_account", "web_app"}

    def _plan_text(self, product: str, p: dict[str, Any]) -> str:
        rg = p.get("resource_group", "undefined")
        loc = p.get("location", "undefined")
        name = p.get("name", "undefined")
        if product == "storage_account":
            return f"Deploy storage account '{name}' in location '{loc}' to resource group '{rg}'"
        if product == "web_app":
            plan_name = p.get("plan", {}).get("name", "undefined")
            return (
                f"Deploy web app '{name}' with plan '{plan_name}' "
                f"in location '{loc}' to resource group '{rg}'"
            )
        return f"Bicep backend does not support product: {product}"

    async def plan(self, spec: dict[str, Any]) -> PlanResult:
        product = spec.get("product")
        if product not in self.SUPPORTED:
            return False, f"Bicep backend does not support product: {product}"
        p = spec.get("parameters", {})
        return True, self._plan_text(product, p)

    async def apply(self, spec: dict[str, Any]) -> ApplyResult:
        return False, {"message": "Bicep backend apply not implemented"}
