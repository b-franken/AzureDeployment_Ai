from __future__ import annotations

from typing import Any


class TerraformBackend:
    async def plan(self, spec: dict[str, Any]) -> tuple[bool, str]:
        product = spec.get("product")
        p = spec.get("parameters", {})

        if not product:
            return False, "Product not specified"

        rg = p.get("resource_group", "undefined")
        loc = p.get("location", "undefined")
        name = p.get("name", "undefined")

        plan = (
            f"Terraform plan for {product} '{name}' in '{loc}' (resource group: {rg})"
        )
        return True, plan

    async def apply(self, spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        return False, {"message": "Terraform backend apply not implemented"}
