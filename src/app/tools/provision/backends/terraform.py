from __future__ import annotations

from typing import Any

from .base import ApplyResult, Backend, PlanResult


class TerraformBackend(Backend):
    def _plan_text(self, product: str, p: dict[str, Any]) -> str:
        rg = p.get("resource_group", "undefined")
        loc = p.get("location", "undefined")
        name = p.get("name", "undefined")
        if product == "web_app":
            plan_name = p.get("plan", {}).get("name", "undefined")
            return (
                f"Terraform plan for web_app '{name}' in '{loc}' "
                f"(resource group: {rg}, plan: {plan_name})"
            )
        return f"Terraform plan for {product} '{name}' in '{loc}' (resource group: {rg})"

    async def plan(self, spec: dict[str, Any]) -> PlanResult:
        product = spec.get("product")
        if not product:
            return False, "Product not specified"
        p = spec.get("parameters", {})
        return True, self._plan_text(product, p)

    async def apply(self, spec: dict[str, Any]) -> ApplyResult:
        return False, {"message": "Terraform backend apply not implemented"}
