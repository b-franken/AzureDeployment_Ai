from __future__ import annotations

import logging
import uuid
from typing import Any

from app.common.envs import ALLOWED_ENVS, normalize_env
from app.core.config import settings
from app.tools.base import Tool, ToolResult

from .actions.deployment import store_pending_deployment
from .actions.registry import action_names_with_aliases, resolve_action
from .clients import get_clients
from .codegen.bicep import generate_bicep_code
from .codegen.terraform import generate_terraform_code
from .logic.defaults import apply_intelligent_defaults
from .logic.preview import (
    build_resource_definition,
    build_resource_preview,
    estimate_basic_cost,
    extract_resource_summary,
    get_resource_display_name,
)
from .logic.resolve import resolve_action_intelligently
from .logic.suggestions import provide_helpful_suggestions
from .logic.validate import validate_and_suggest
from .tags import standard_tags
from .utils.response import err, ok
from .validation import DeploymentValidator, ValidationLevel

logger = logging.getLogger(__name__)


class AzureProvision(Tool):
    name = "azure_provision"
    description = (
        "Provision Azure resources using natural language or structured commands."
        " Supports intelligent parsing of everyday language for DevOps tasks."
    )
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Natural language description or specific action name",
            },
            "subscription_id": {"type": "string"},
            "resource_group": {"type": "string"},
            "location": {"type": "string", "enum": list(settings.azure.allowed_locations)},
            "name": {"type": "string"},
            "sku": {"type": "string"},
            "access_tier": {"type": "string", "enum": ["Hot", "Cool", "Archive"]},
            "address_prefix": {"type": "string"},
            "subnet_prefix": {"type": "string"},
            "plan": {"type": "string"},
            "runtime": {"type": "string"},
            "linux": {"type": "boolean"},
            "https_only": {"type": "boolean"},
            "always_on": {"type": "boolean"},
            "ftps_state": {"type": "string"},
            "min_tls_version": {"type": "string"},
            "health_check_path": {"type": "string"},
            "client_affinity_enabled": {"type": "boolean"},
            "vnet_subnet_id": {"type": "string"},
            "vnet_route_all_enabled": {"type": "boolean"},
            "app_settings": {"type": "object"},
            "tags": {"type": "object"},
            "dry_run": {"type": "boolean", "default": True},
            "vnet_name": {"type": "string"},
            "subnet_name": {"type": "string"},
            "vm_size": {"type": "string"},
            "admin_username": {"type": "string"},
            "ssh_public_key": {"type": "string"},
            "dns_prefix": {"type": "string"},
            "node_count": {"type": "integer"},
            "vault_name": {"type": "string"},
            "tenant_id": {"type": "string"},
            "server_name": {"type": "string"},
            "sql_admin_user": {"type": "string"},
            "sql_admin_password": {"type": "string"},
            "force": {"type": "boolean", "default": False},
            "env": {"type": "string", "enum": list(ALLOWED_ENVS)},
            "owner": {"type": "string"},
        },
        "required": ["action"],
        "additionalProperties": True,
    }

    async def run(self, action: str, **kwargs: Any) -> ToolResult:
        try:
            params = dict(kwargs)
            logger.info("Azure provision tool called with action='%s' params=%s", action, params)

            env_in = str(params.get("env") or params.get("environment") or "dev")
            try:
                canon_env = normalize_env(env_in)
            except Exception:
                canon_env = "dev"
            params["env"] = canon_env
            params["environment"] = canon_env

            canonical_action = resolve_action_intelligently(action, params)
            if not canonical_action:
                available = list(action_names_with_aliases())[:10]
                suggestions = provide_helpful_suggestions(action)
                lines = [
                    f"Unknown action: {action}",
                    f"Try: {', '.join(suggestions)}",
                    f"Available actions: {', '.join(available)}",
                ]
                return err("Could not understand request", "\n\n".join(lines))

            apply_intelligent_defaults(canonical_action, params)

            is_valid, validation_msg = validate_and_suggest(canonical_action, params)
            if not is_valid:
                return err("Invalid parameters", validation_msg)

            logger.info(
                f"Tool execution check: dry_run={params.get('dry_run', True)}, params={params}"
            )

            if params.get("dry_run", True):
                logger.info("Entering DRY RUN mode - generating preview only")
                deployment_id = str(uuid.uuid4())[:8]
                bicep_code = generate_bicep_code(canonical_action, params)
                terraform_code = generate_terraform_code(canonical_action, params)
                resource_preview = build_resource_preview(canonical_action, params)
                cost_estimate = estimate_basic_cost(canonical_action, params)

                resource_def = build_resource_definition(canonical_action, params)
                validation_summary: dict[str, Any] | None = None
                try:
                    validator = DeploymentValidator(level=ValidationLevel.STANDARD)
                    report = await validator.validate_deployment(
                        resources=[resource_def],
                        context={
                            "deployment_id": deployment_id,
                            "environment": canon_env,
                            "initiated_by": "user",
                            "all_resources": [resource_def],
                        },
                    )
                    top = [r for r in report.results if not r.passed][:5]
                    validation_summary = {
                        "level": report.level.value,
                        "warnings": report.warnings,
                        "errors": report.errors,
                        "critical": report.critical,
                        "recommendations": report.recommendations[:5],
                        "failed": [
                            {"rule": r.rule_id, "message": r.message, "severity": r.severity}
                            for r in top
                        ],
                    }
                except Exception as e:
                    validation_summary = {"error": str(e)}

                summary = {
                    "deployment_id": deployment_id,
                    "action": canonical_action,
                    "status": "deployment_preview",
                    "summary": f"Ready to deploy {get_resource_display_name(canonical_action)} '{params.get('name', 'resource')}' in {params.get('location', 'westeurope')}",
                    "resource_details": resource_preview,
                    "cost_estimate": cost_estimate,
                    "infrastructure_code": {"bicep": bicep_code, "terraform": terraform_code},
                    "validation": validation_summary,
                    "next_steps": [
                        "Review the deployment details and infrastructure code above",
                        "To proceed with deployment, confirm with: 'deploy confirmed' or 'execute deployment'",
                        "To cancel: 'cancel deployment' or 'abort'",
                    ],
                    "warning": "This will create real Azure resources and may incur costs",
                    "environment": params.get("environment", "dev"),
                    "subscription_id": params.get("subscription_id"),
                    "resource_group": params.get("resource_group"),
                    "location": params.get("location"),
                }
                return ok(f"Deployment Preview: {canonical_action}", summary)

            logger.info("DRY RUN check passed - proceeding with ACTUAL DEPLOYMENT")
            logger.info(f"Creating Azure clients for subscription: {params.get('subscription_id')}")
            clients = await get_clients(params.get("subscription_id"))
            env = params.get("env", "dev")
            owner = params.get("owner", "devops-bot")
            extra_tags = params.get("tags", {})
            tags = standard_tags(extra_tags, owner, env)

            _, action_func = resolve_action(canonical_action)
            if not action_func:
                logger.error(f"Action function not found for: {canonical_action}")
                return err("Action not implemented", f"Action {canonical_action} is not available")

            logger.info(
                f"Action function resolved: {action_func.__name__} for action: {canonical_action}"
            )

            resource_definition = build_resource_definition(canonical_action, params)
            deployment_id = str(uuid.uuid4())[:8]
            deployment_data = {
                "action": canonical_action,
                "parameters": params,
                "environment": env,
                "tags": tags,
                "resources": [resource_definition],
                "subscription_id": params.get("subscription_id"),
                "resource_group": params.get("resource_group"),
                "location": params.get("location"),
                "initiated_by": "user",
            }
            store_pending_deployment(deployment_id, deployment_data)

            params["dry_run"] = False
            params_without_tags = {k: v for k, v in params.items() if k != "tags"}
            logger.info(f"Calling action function with params: {params_without_tags}")
            status, payload = await action_func(clients=clients, tags=tags, **params_without_tags)
            logger.info(f"Action function returned: status={status}, payload={payload}")
            if status == "plan":
                detailed_plan = {
                    "deployment_id": deployment_id,
                    "deployment_plan": payload,
                    "action": canonical_action,
                    "parameters": params,
                    "confirmation_required": False,
                    "next_steps": [],
                    "estimated_resources": extract_resource_summary(payload),
                    "environment": env,
                    "resource_group": params.get("resource_group"),
                    "location": params.get("location"),
                }
                return ok(f"Deployment Executed Plan - {canonical_action}", detailed_plan)

            bicep_code = generate_bicep_code(canonical_action, params)
            terraform_code = generate_terraform_code(canonical_action, params)
            resource_preview = build_resource_preview(canonical_action, params)
            cost_estimate = estimate_basic_cost(canonical_action, params)

            executed = {
                "deployment_id": deployment_id,
                "action": canonical_action,
                "status": "deployment_completed",
                "summary": f"Successfully deployed {get_resource_display_name(canonical_action)} '{params.get('name', 'resource')}' in {params.get('location', 'westeurope')}",
                "parameters": params,
                "result": payload,
                "environment": env,
                "resource_details": resource_preview,
                "cost_estimate": cost_estimate,
                "infrastructure_code": {"bicep": bicep_code, "terraform": terraform_code},
                "subscription_id": params.get("subscription_id"),
                "resource_group": params.get("resource_group"),
                "location": params.get("location"),
            }
            return ok(f"Deployment Executed - {canonical_action}", executed)
        except Exception as e:
            msg = str(e)
            if "AccountKey" in msg or "password" in msg.lower():
                msg = "[Sensitive information redacted]"
            return err("Execution error", msg)
