from __future__ import annotations

import importlib
import json
import logging
from typing import Any, Literal, cast

from app.ai.nlu import parse_provision_request
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
BackendName = Literal["sdk", "terraform", "bicep", "avm"]


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
    except Exception as exc:
        logger.debug("Failed to load AVM Bicep backend: %s", exc)
        return None


def _choose_bicep_backend() -> tuple[Literal["avm", "legacy"], Any]:
    avm_cls = _load_avm_backend_cls()
    if avm_cls is not None:
        return "avm", avm_cls()
    return "legacy", LegacyBicepBackend()


class ProvisionOrchestrator(Tool):
    name = "provision_orchestrator"
    description = "Provision Azure products using natural language or structured specifications"
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "Natural language request or product specification",
            },
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
                "enum": ["auto", "terraform", "bicep", "avm", "sdk"],
                "default": "auto",
            },
            "env": {"type": "string", "enum": list(ALLOWED_ENVS), "default": "dev"},
            "plan_only": {"type": "boolean", "default": False},
            "parameters": {"type": "object", "additionalProperties": True},
            "subscription_id": {"type": "string"},
            "resource_group": {"type": "string"},
            "location": {"type": "string"},
            "include_cost_estimate": {"type": "boolean", "default": True},
        },
        "additionalProperties": False,
    }

    async def run(
        self,
        request: str | None = None,
        product: Product | None = None,
        parameters: dict[str, Any] | None = None,
        backend: str = "auto",
        env: Env = "dev",
        plan_only: bool = False,
        subscription_id: str | None = None,
        resource_group: str | None = None,
        location: str | None = None,
        include_cost_estimate: bool = True,
    ) -> ToolResult:
        try:
            if request and not product:
                nlu_result = parse_provision_request(request)

                if nlu_result.confidence < 0.3:
                    return _err(
                        "Could not understand request",
                        {
                            "input": request,
                            "confidence": nlu_result.confidence,
                            "suggestion": (
                                "Please provide more specific details about the resource "
                                "you want to provision"
                            ),
                        },
                    )

                if backend in ["avm", "auto"] and nlu_result.confidence > 0.5:
                    try:
                        mode, avm_backend = _choose_bicep_backend()
                        if mode == "avm":
                            from .backends.avm_bicep import ProvisionContext

                            ctx = ProvisionContext(
                                subscription_id=subscription_id or "",
                                resource_group=resource_group
                                or nlu_result.parameters.get("resource_group", ""),
                                location=location or nlu_result.context.get("location", "westeurope"),
                                environment=env,
                                tags=nlu_result.context.get("tags", {}),
                            )

                            preview = await avm_backend.plan_from_nlu(
                                nlu_result.__dict__, ctx, plan_only
                            )

                            result = {
                                "backend": "avm-bicep",
                                "environment": env,
                                "bicep": preview.rendered,
                                "what_if": preview.what_if,
                            }

                            if include_cost_estimate and preview.cost_estimate:
                                result["cost_estimate"] = preview.cost_estimate

                            if plan_only:
                                return _ok("AVM Bicep plan generated from natural language", result)
                            deploy_result = await avm_backend.apply(ctx, preview.bicep_path)
                            result["deployment"] = deploy_result
                            return _ok("AVM Bicep deployment executed", result)
                    except Exception as avm_error:
                        logger.warning(
                            "AVM backend failed, attempting intelligent fallback",
                            error=str(avm_error),
                            confidence=nlu_result.confidence,
                            exc_info=True,
                        )
                        return await self._intelligent_fallback(
                            request=request,
                            subscription_id=subscription_id,
                            resource_group=resource_group,
                            location=location,
                            env=env,
                            plan_only=plan_only,
                            include_cost_estimate=include_cost_estimate,
                        )

                try:
                    orchestrator_args = nlu_result.to_orchestrator_args()
                    if orchestrator_args:
                        return await self.run(
                            product=orchestrator_args["product"],
                            parameters=orchestrator_args["parameters"],
                            backend=orchestrator_args.get("backend", backend),
                            env=orchestrator_args.get("env", env),
                            plan_only=orchestrator_args.get("plan_only", plan_only),
                            subscription_id=subscription_id,
                            resource_group=resource_group,
                            location=location,
                            include_cost_estimate=include_cost_estimate,
                        )
                except Exception as orchestrator_error:
                    logger.warning(
                        "Orchestrator args processing failed, attempting intelligent fallback",
                        error=str(orchestrator_error),
                        args=orchestrator_args if 'orchestrator_args' in locals() else None,
                        exc_info=True,
                    )
                    return await self._intelligent_fallback(
                        request=request,
                        subscription_id=subscription_id,
                        resource_group=resource_group,
                        location=location,
                        env=env,
                        plan_only=plan_only,
                        include_cost_estimate=include_cost_estimate,
                    )

            if not product or not parameters:
                return _err(
                    "Invalid request",
                    "Either provide a natural language request or specify product and parameters",
                )

            try:
                spec = ProvisionSpec(
                    product=product,
                    env=env,
                    backend=cast("BackendLiteral", backend if backend != "avm" else "auto"),
                    plan_only=plan_only,
                    parameters=parameters,
                ).dict()
            except Exception as e:
                return _err("Invalid specification", str(e))

            chosen: BackendName = pick_backend(
                env=spec["env"],
                requested=cast("BackendLiteral", backend if backend != "avm" else "auto"),
                plan_only=spec["plan_only"],
            )

            if backend == "avm":
                chosen = "avm"

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
                chosen_label = "bicep-legacy"
            elif chosen == "avm":
                mode, be = _choose_bicep_backend()
                chosen_label = "bicep-avm" if mode == "avm" else "bicep-legacy"
            else:
                be = SdkBackend()
                chosen_label = "sdk"

            if spec["plan_only"]:
                ok_plan, plan_out = await be.plan(spec)

                plan_result: dict[str, Any] = {
                    "backend": chosen_label,
                    "plan": plan_out,
                }

                if include_cost_estimate and chosen == "avm":
                    try:
                        mod = importlib.import_module(
                            ".backends.avm_bicep.emitters.cost_estimator", package=__package__
                        )
                        Estimator = getattr(mod, "CostEstimator", None)
                        if Estimator is not None:
                            estimator = Estimator()
                            plan_result["cost_estimate"] = estimator.estimate_monthly_cost(
                                {"resources": [spec["parameters"]]}
                            )
                    except Exception as exc:
                        logger.debug("Failed to estimate costs: %s", exc)

                return (
                    _ok(f"{chosen_label} plan", plan_result)
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
            logger.warning(
                "Primary backend failed, attempting intelligent fallback",
                chosen=chosen_label,
                error=str(e),
                exc_info=True,
            )
            return await self._intelligent_fallback(
                request=request,
                subscription_id=subscription_id,
                resource_group=resource_group,
                location=location,
                env=env,
                plan_only=plan_only,
                include_cost_estimate=include_cost_estimate,
            )


    async def _intelligent_fallback(
        self,
        request: str | None,
        subscription_id: str | None,
        resource_group: str | None,
        location: str | None,
        env: Env,
        plan_only: bool,
        include_cost_estimate: bool,
    ) -> ToolResult:
        """Fallback to intelligent Azure provisioning with agents when primary backends fail."""
        try:
            from app.tools.azure.intelligent_provision import IntelligentAzureProvision
            
            logger.info(
                "Falling back to intelligent Azure provisioning with agents",
                request=request,
                subscription_id=subscription_id,
                resource_group=resource_group,
                location=location,
                environment=env,
            )
            
            intelligent_tool = IntelligentAzureProvision()
            
            fallback_result = await intelligent_tool.run(
                request=request or "",
                subscription_id=subscription_id,
                resource_group=resource_group,
                location=location,
                environment=env,
                dry_run=plan_only,
                confirmed=not plan_only,
                include_cost_estimate=include_cost_estimate,
            )
            
            if fallback_result.get("ok"):
                logger.info(
                    "Intelligent fallback succeeded",
                    summary=fallback_result.get("summary"),
                )
                
                enhanced_result = fallback_result.copy()
                enhanced_result["backend"] = "intelligent-agents-fallback"
                enhanced_result["fallback_reason"] = "Primary AVM/Terraform/Bicep backends failed"
                
                return enhanced_result
            else:
                logger.error(
                    "Intelligent fallback also failed",
                    summary=fallback_result.get("summary"),
                    output=fallback_result.get("output"),
                )
                return _err(
                    "All provisioning methods failed",
                    {
                        "primary_backend_error": "AVM/Terraform/Bicep failed",
                        "fallback_error": fallback_result.get("output"),
                        "suggestion": (
                            "Check Azure credentials, subscription access, "
                            "and resource naming constraints"
                        ),
                    },
                )
                
        except Exception as fallback_error:
            logger.error(
                "Critical error in intelligent fallback",
                error=str(fallback_error),
                exc_info=True,
            )
            return _err(
                "Critical provisioning failure",
                {
                    "error": "Both primary and fallback provisioning methods failed",
                    "details": str(fallback_error),
                },
            )


logger = logging.getLogger(__name__)
