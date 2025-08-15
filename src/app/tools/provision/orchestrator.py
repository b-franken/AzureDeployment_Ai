from __future__ import annotations

import json
from typing import Any, Literal, cast

from app.tools.base import Tool, ToolResult

from .backends import BicepBackend, SdkBackend, TerraformBackend
from .models import ProvisionSpec
from .router import pick_backend

Product = Literal["web_app", "storage_account"]
Backend = Literal["auto", "terraform", "bicep", "sdk"]
Env = Literal["dev", "tst", "acc", "prod"]


def _to_str(obj: Any) -> str:
    return (
        obj
        if isinstance(obj, str)
        else json.dumps(obj, default=str, ensure_ascii=False)
    )


def _ok(summary: str, obj: Any) -> ToolResult:
    return {"ok": True, "summary": summary, "output": _to_str(obj)}


def _err(summary: str, obj: Any) -> ToolResult:
    return {"ok": False, "summary": summary, "output": _to_str(obj)}


class ProvisionOrchestrator(Tool):
    name = "provision_orchestrator"
    description = "Provision Azure products using a selected backend"
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "product": {"type": "string", "enum": ["web_app", "storage_account"]},
            "backend": {
                "type": "string",
                "enum": ["auto", "terraform", "bicep", "sdk"],
                "default": "auto",
            },
            "env": {
                "type": "string",
                "enum": ["dev", "tst", "acc", "prod"],
                "default": "dev",
            },
            "plan_only": {"type": "boolean", "default": True},
            "parameters": {"type": "object", "additionalProperties": True},
        },
        "required": ["product", "parameters"],
        "additionalProperties": False,
    }

    async def run(
        self,
        product: Product,
        parameters: dict[str, Any],
        backend: Backend = "auto",
        env: Env = "dev",
        plan_only: bool = True,
    ) -> ToolResult:
        try:
            spec = ProvisionSpec(
                product=product,
                env=env,
                backend=backend,
                plan_only=plan_only,
                parameters=parameters,
            ).dict()
        except Exception as e:
            return _err("Invalid specification", str(e))

        chosen = cast(
            Backend, pick_backend(spec["product"], spec["env"], spec["backend"])
        )

        if chosen == "sdk":
            be: SdkBackend | TerraformBackend | BicepBackend = SdkBackend()
        elif chosen == "terraform":
            be = TerraformBackend()
        elif chosen == "bicep":
            be = BicepBackend()
        else:
            return _err("Unknown backend", chosen)

        ok, plan_text = await be.plan(spec)
        if not ok:
            return _err(f"{chosen} plan failed", plan_text)

        if plan_only:
            return _ok(f"{chosen} plan", plan_text)

        if isinstance(be, TerraformBackend):
            return _err(
                "terraform apply is not supported",
                "enable plan_only or choose sdk or bicep",
            )

        ok, outputs = await be.apply(spec)
        if not ok:
            return _err(f"{chosen} apply failed", outputs)

        return _ok(f"{chosen} applied", outputs)
