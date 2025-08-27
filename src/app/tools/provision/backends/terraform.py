from __future__ import annotations

from typing import Any

from ...azure.utils.terraform_runner import TerraformError, plan_and_apply
from .base import Backend


class TerraformBackend(Backend):
    async def plan(self, spec: dict[str, Any]) -> tuple[bool, Any]:
        try:
            res = await plan_and_apply(spec, plan_only=True)
            return True, res
        except TerraformError as e:
            return False, {"error": "terraform_plan_failed", "details": str(e)}
        except Exception as e:
            return False, {"error": "terraform_plan_error", "details": str(e)}

    async def apply(self, spec: dict[str, Any]) -> tuple[bool, Any]:
        try:
            res = await plan_and_apply(spec, plan_only=False)
            return True, res
        except TerraformError as e:
            return False, {"error": "terraform_apply_failed", "details": str(e)}
        except Exception as e:
            return False, {"error": "terraform_apply_error", "details": str(e)}
