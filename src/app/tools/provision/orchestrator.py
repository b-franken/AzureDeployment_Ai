from __future__ import annotations

import importlib
import json
from typing import Any, Literal, cast

from app.common.envs import ALLOWED_ENVS, Env
from app.tools.base import Tool, ToolResult

from .backends import BicepBackend as LegacyBicepBackend
from .backends import SdkBackend, TerraformBackend
from .backends.base import Backend
from .models import Backend as BackendLiteral
from .models import ProvisionSpec
from .router import pick_backend

Product = Literal[
    "web_app",
    "storage_account",
    "aks_cluster",
    "container_registry",
    "api_management",
    "event_hub",
]
BackendName = Literal["sdk", "terraform", "bicep"]


def _to_str(obj: Any) -> str:
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8", errors="replace")
        except Exception:
            return str(obj)
    return obj if isinstance(obj, str) else json.dumps(obj, default=str, ensure_ascii=False)


def _ok(summary: str, obj: Any) -> ToolResult:
    return {"ok": True, "summary": summary, "output": _to_str(obj)}


def _err(summary: str, obj: Any) -> ToolResult:
    return {"ok": False, "summary": summary, "output": _to_str(obj)}


def _load_avm_backend_cls() -> Any | None:
    try:
        mod = importlib.import_module(".backends.avm_bicep", package=__package__)
        return mod.BicepAvmBackend
    except Exception:
        return None


def _choose_bicep_backend() -> tuple[Literal["avm", "legacy"], Backend]:
    avm_cls = _load_avm_backend_cls()
    if avm_cls is not None:
        return "avm", cast(Backend, avm_cls())
    return "legacy", LegacyBicepBackend()


class ProvisionOrchestrator(Tool):
    name = "provision_orchestrator"
    description = "Provision Azure products using a selected backend"
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "product": {
                "type": "string",
                "enum": [
                    "web_app",
                    "storage_account",
                    "aks_cluster",
                    "container_registry",
                    "api_management",
                    "event_hub",
                ],
            },
            "backend": {
                "type": "string",
                "enum": ["auto", "terraform", "bicep", "sdk"],
                "default": "auto",
            },
            "env": {"type": "string", "enum": list(ALLOWED_ENVS), "default": "dev"},
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
        backend: BackendLiteral = "auto",
        env: Env = "dev",
        plan_only: bool = True,
    ) -> ToolResult:
        try:
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

            chosen: BackendName = pick_backend(
                env=spec["env"], requested=spec["backend"], plan_only=spec["plan_only"]
            )

            be: Backend
            chosen_label: str
            if chosen == "sdk":
                be = SdkBackend()
                chosen_label = "sdk"
            elif chosen == "terraform":
                be = TerraformBackend()
                chosen_label = "terraform"
            elif chosen == "bicep":
                mode, be = _choose_bicep_backend()
                chosen_label = "bicep-avm" if mode == "avm" else "bicep"
            else:
                be = SdkBackend()
                chosen_label = "sdk"

            if spec["plan_only"]:
                ok_plan, plan_out = await be.plan(spec)
                return (
                    _ok(f"{chosen_label} plan", plan_out)
                    if ok_plan
                    else _err(f"{chosen_label} plan failed", plan_out)
                )

            ok_apply, apply_out = await be.apply(spec)
            return (
                _ok(f"{chosen_label} apply", apply_out)
                if ok_apply
                else _err(f"{chosen_label} apply failed", apply_out)
            )
        except Exception as e:
            return _err("orchestrator error", str(e))
