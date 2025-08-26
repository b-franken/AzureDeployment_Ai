from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.ai.nlu import parse_provision_request
from app.common.envs import ALLOWED_ENVS, normalize_env
from app.core.config import settings
from app.tools.base import Tool, ToolResult

from .actions.deployment import store_pending_deployment
from .actions.registry import action_names_with_aliases, resolve_action
from .clients import get_clients
from .tags import standard_tags
from .validators import validate_location, validate_name

logger = logging.getLogger(__name__)


def _ok(summary: str, obj: dict | str = "") -> ToolResult:
    return {
        "ok": True,
        "summary": summary,
        "output": (obj if isinstance(obj, str) else json.dumps(obj, default=str, indent=2)),
    }


def _err(summary: str, msg: str) -> ToolResult:
    return {"ok": False, "summary": summary, "output": msg}


def _dry(summary: str, payload: dict) -> ToolResult:
    return _ok(summary, {"dry_run": True, **payload})


def _resolve_action_intelligently(action_input: str, params: dict[str, Any]) -> str:
    r = parse_provision_request(action_input)
    if r.parameters:
        params.update(r.parameters)
    canon, _ = resolve_action(r.action)
    if canon:
        return canon
    canon2, _ = resolve_action(action_input)
    if canon2:
        return canon2
    if r.resource_type and params.get("name"):
        return f"create_{r.resource_type}"
    return "create_rg"


def _apply_intelligent_defaults(action: str, params: dict[str, Any]) -> None:
    base_name = params.get("name", "")
    env = params.get("environment", "dev")

    if action in ["create_rg", "create_resource_group"]:
        if "name" in params and "resource_group" not in params:
            params["resource_group"] = params["name"]
        if "resource_group" in params and "name" not in params:
            params["name"] = params["resource_group"]
        if "location" not in params:
            params["location"] = "westeurope"

    elif action in ["create_storage", "create_storage_account"]:
        if "resource_group" not in params and base_name:
            params["resource_group"] = f"{base_name}-{env}-rg"
        if "location" not in params:
            params["location"] = "westeurope"
        if "sku" not in params:
            params["sku"] = "Standard_LRS"
        if "access_tier" not in params:
            params["access_tier"] = "Hot"

    elif action in ["create_webapp", "create_web_app"]:
        if "plan" not in params and base_name:
            params["plan"] = f"{base_name}-{env}-plan"
        if "resource_group" not in params and base_name:
            params["resource_group"] = f"{base_name}-{env}-rg"
        if "location" not in params:
            params["location"] = "westeurope"

    elif action == "create_vm":
        if "resource_group" not in params and base_name:
            params["resource_group"] = f"{base_name}-{env}-rg"
        if "location" not in params:
            params["location"] = "westeurope"
        if "vm_size" not in params:
            params["vm_size"] = "Standard_B2s"
        if "admin_username" not in params:
            params["admin_username"] = "azureuser"
        if "vnet_name" not in params and base_name:
            params["vnet_name"] = f"{base_name}-{env}-vnet"
        if "subnet_name" not in params:
            params["subnet_name"] = "default"

    elif action == "create_keyvault":
        if "vault_name" not in params and "name" in params:
            params["vault_name"] = params["name"]
        if "resource_group" not in params and params.get("vault_name"):
            params["resource_group"] = f"{params['vault_name']}-{env}-rg"
        if "location" not in params:
            params["location"] = "westeurope"
        if "tenant_id" not in params:
            params["tenant_id"] = "common"

    elif action == "create_aks":
        if "resource_group" not in params and base_name:
            params["resource_group"] = f"{base_name}-{env}-rg"
        if "location" not in params:
            params["location"] = "westeurope"
        if "dns_prefix" not in params and base_name:
            params["dns_prefix"] = f"{base_name}-{env}"
        if "node_count" not in params:
            params["node_count"] = 2

    elif action == "create_acr":
        if "resource_group" not in params and base_name:
            params["resource_group"] = f"{base_name}-{env}-rg"
        if "location" not in params:
            params["location"] = "westeurope"
        if "sku" not in params:
            params["sku"] = "Basic"

    elif action in ["create_sql", "create_sql_server"]:
        if "resource_group" not in params and base_name:
            params["resource_group"] = f"{base_name}-{env}-rg"
        if "location" not in params:
            params["location"] = "westeurope"
        if "server_name" not in params and "name" in params:
            params["server_name"] = params["name"]
        if "sql_admin_user" not in params:
            params["sql_admin_user"] = "sqladmin"


def _validate_and_suggest(action: str, params: dict[str, Any]) -> tuple[bool, str]:
    required_by_action = {
        "create_rg": ["resource_group", "location"],
        "create_resource_group": ["resource_group", "location"],
        "create_storage": ["resource_group", "location", "name"],
        "create_storage_account": ["resource_group", "location", "name"],
        "create_webapp": ["resource_group", "name", "plan"],
        "create_web_app": ["resource_group", "name", "plan"],
        "create_vm": [
            "resource_group",
            "location",
            "name",
            "vm_size",
            "admin_username",
        ],
        "create_keyvault": ["resource_group", "location", "vault_name", "tenant_id"],
        "create_aks": ["resource_group", "location", "name", "dns_prefix"],
        "create_acr": ["resource_group", "location", "name"],
        "create_sql": [
            "resource_group",
            "location",
            "server_name",
            "sql_admin_user",
            "sql_admin_password",
        ],
        "create_vnet": ["resource_group", "location", "name", "address_prefix"],
    }

    if action not in required_by_action:
        return True, ""

    missing = [p for p in required_by_action[action] if p not in params or not params[p]]
    if missing:
        suggestions = []
        for param in missing:
            if param == "location":
                suggestions.append("location: westeurope, eastus, northeurope, uksouth")
            elif param == "resource_group":
                suggestions.append("resource_group: your-project-dev-rg")
            elif param == "name":
                suggestions.append("name: unique name for your resource")
            else:
                suggestions.append(f"{param}: required parameter")

        return (
            False,
            f"Missing: {', '.join(missing)}. Suggestions: {'; '.join(suggestions)}",
        )

    if params.get("location") and not validate_location(params["location"]):
        return (
            False,
            "Invalid location. Use: westeurope, eastus, northeurope, or uksouth",
        )

    validation_rules = {
        "storage": ("name", 3, 24, "lowercase letters and numbers only"),
        "webapp": ("name", 2, 60, "letters, numbers, and hyphens"),
        "acr": ("name", 5, 50, "letters and numbers only"),
        "sql_server": ("server_name", 1, 63, "letters, numbers, and hyphens"),
    }

    for resource_type, (field, min_len, max_len, desc) in validation_rules.items():
        if action.endswith(resource_type) and field in params:
            if not validate_name(resource_type, params[field]):
                return (
                    False,
                    f"Invalid {field}: must be {min_len}-{max_len} characters, {desc}",
                )

    return True, ""


def _extract_resource_summary(payload: dict) -> dict[str, str]:
    """Extract a human-readable summary of resources from deployment payload."""
    summary = {}

    if isinstance(payload, dict):
        # Extract key resource information
        if "resource_group" in payload:
            summary["Resource Group"] = payload["resource_group"]
        if "name" in payload:
            summary["Resource Name"] = payload["name"]
        if "location" in payload:
            summary["Location"] = payload["location"]
        if "sku" in payload:
            summary["SKU/Tier"] = payload["sku"]
        if "resource_type" in payload:
            summary["Resource Type"] = payload["resource_type"]

        # Extract cost estimates if available
        if "cost_estimate" in payload:
            cost = payload["cost_estimate"]
            if isinstance(cost, dict):
                if "monthly_total" in cost:
                    summary["Estimated Monthly Cost"] = f"${cost['monthly_total']}"
                if "setup_cost" in cost:
                    summary["Setup Cost"] = f"${cost['setup_cost']}"

        # Extract network/connectivity info
        if "dns_prefix" in payload:
            summary["DNS Prefix"] = payload["dns_prefix"]
        if "address_prefix" in payload:
            summary["Network Range"] = payload["address_prefix"]
        if "node_count" in payload:
            summary["Node Count"] = str(payload["node_count"])

    return summary


def _build_resource_definition(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Build a structured resource definition from action and parameters."""
    resource_type_map = {
        "create_rg": "Microsoft.Resources/resourceGroups",
        "create_resource_group": "Microsoft.Resources/resourceGroups",
        "create_storage": "Microsoft.Storage/storageAccounts",
        "create_webapp": "Microsoft.Web/sites",
        "create_aks": "Microsoft.ContainerService/managedClusters",
        "create_acr": "Microsoft.ContainerRegistry/registries",
        "create_keyvault": "Microsoft.KeyVault/vaults",
        "create_vm": "Microsoft.Compute/virtualMachines",
        "create_sql": "Microsoft.Sql/servers",
        "create_vnet": "Microsoft.Network/virtualNetworks",
    }

    return {
        "name": params.get("name", "unnamed-resource"),
        "type": resource_type_map.get(action, "Unknown"),
        "location": params.get("location", "westeurope"),
        "properties": {
            k: v for k, v in params.items() if k not in ["name", "location", "resource_group"]
        },
        "resource_group": params.get("resource_group"),
        "sku": params.get("sku"),
        "action": action,
    }


def _build_resource_preview(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Build a detailed resource preview for user review."""
    preview = {
        "Resource Type": _get_resource_display_name(action),
        "Name": params.get("name", "Not specified"),
        "Location": params.get("location", "westeurope"),
        "Resource Group": params.get("resource_group", "Not specified"),
        "Environment": params.get("environment", "dev"),
    }

    # Add action-specific details
    if action in ["create_storage", "create_storage_account"]:
        preview.update(
            {
                "SKU/Performance": params.get("sku", "Standard_LRS"),
                "Access Tier": params.get("access_tier", "Hot"),
                "Redundancy": "Locally Redundant"
                if params.get("sku") == "Standard_LRS"
                else "Standard",
            }
        )
    elif action in ["create_webapp", "create_web_app"]:
        preview.update(
            {
                "Runtime": params.get("runtime", "Not specified"),
                "App Service Plan": params.get(
                    "plan", f"{params.get('name', 'app')}-{params.get('environment', 'dev')}-plan"
                ),
                "HTTPS Only": params.get("https_only", True),
            }
        )
    elif action == "create_aks":
        preview.update(
            {
                "DNS Prefix": params.get(
                    "dns_prefix", f"{params.get('name', 'aks')}-{params.get('environment', 'dev')}"
                ),
                "Node Count": params.get("node_count", 2),
                "Node VM Size": params.get("node_vm_size", "Standard_DS2_v2"),
            }
        )
    elif action == "create_vm":
        preview.update(
            {
                "VM Size": params.get("vm_size", "Standard_B2s"),
                "Admin Username": params.get("admin_username", "azureuser"),
                "Operating System": "Linux (Ubuntu)" if not params.get("windows") else "Windows",
            }
        )

    return preview


def _get_resource_display_name(action: str) -> str:
    """Get a human-readable resource type name."""
    display_names = {
        "create_rg": "Resource Group",
        "create_resource_group": "Resource Group",
        "create_storage": "Storage Account",
        "create_webapp": "Web App",
        "create_aks": "Azure Kubernetes Service",
        "create_acr": "Container Registry",
        "create_keyvault": "Key Vault",
        "create_vm": "Virtual Machine",
        "create_sql": "SQL Server",
        "create_vnet": "Virtual Network",
    }
    return display_names.get(action, action.replace("create_", "").replace("_", " ").title())


def _estimate_basic_cost(action: str, params: dict[str, Any]) -> dict[str, str]:
    """Provide basic cost estimates for common resources."""
    cost_estimates = {
        "create_rg": {
            "setup_cost": "$0.00",
            "monthly_estimate": "$0.00",
            "note": "Resource groups are free",
        },
        "create_storage": {
            "setup_cost": "$0.00",
            "monthly_estimate": "$1-5",
            "note": "Depends on storage usage and redundancy",
        },
        "create_webapp": {
            "setup_cost": "$0.00",
            "monthly_estimate": "$10-50",
            "note": "Depends on App Service Plan tier",
        },
        "create_aks": {
            "setup_cost": "$0.00",
            "monthly_estimate": "$70-200",
            "note": "Based on node count and VM sizes",
        },
        "create_vm": {
            "setup_cost": "$0.00",
            "monthly_estimate": "$30-100",
            "note": "Depends on VM size and usage hours",
        },
        "create_acr": {
            "setup_cost": "$0.00",
            "monthly_estimate": "$5-20",
            "note": "Basic tier ~$5/month, Standard ~$20/month",
        },
    }

    return cost_estimates.get(
        action,
        {
            "setup_cost": "$0.00",
            "monthly_estimate": "Variable",
            "note": "Contact Azure pricing calculator for accurate estimates",
        },
    )


def _provide_helpful_suggestions(original_input: str) -> list[str]:
    suggestions = []

    if "storage" in original_input.lower():
        suggestions.append(
            "create storage account myapp123 in westeurope resource group myapp-dev-rg"
        )
        suggestions.append("create storage mydata in eastus with sku Standard_GRS")

    if "web" in original_input.lower() or "app" in original_input.lower():
        suggestions.append("create web app mywebapp in westeurope resource group myapp-dev-rg")
        suggestions.append("create webapp mysite with runtime python|3.9")

    if "kubernetes" in original_input.lower() or "aks" in original_input.lower():
        suggestions.append("create aks cluster mycluster in westeurope resource group myapp-dev-rg")
        suggestions.append("create kubernetes myk8s with 3 nodes")

    if not suggestions:
        suggestions.extend(
            [
                "create resource group myproject-dev-rg in westeurope",
                "create storage account mydata123 in westeurope",
                "create web app mywebapp in westeurope",
                "create aks cluster mycluster in westeurope",
            ]
        )

    return suggestions


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
            logger.info(f"Azure provision tool called with action='{action}' params={params}")
            dry_run_value = params.get("dry_run", True)
            logger.info(f"Dry run check: params.get('dry_run', True) = {dry_run_value}")
            env_in = str(params.get("env") or params.get("environment") or "dev")
            try:
                canon_env = normalize_env(env_in)
            except Exception:
                canon_env = "dev"
            params["env"] = canon_env
            params["environment"] = canon_env

            canonical_action = _resolve_action_intelligently(action, params)
            if not canonical_action:
                available = list(action_names_with_aliases())[:10]
                suggestions = _provide_helpful_suggestions(action)
                msg_lines = [
                    f"Unknown action: {action}",
                    f"Try: {', '.join(suggestions)}",
                    f"Available actions: {', '.join(available)}",
                ]
                return _err("Could not understand request", "\n\n".join(msg_lines))

            _apply_intelligent_defaults(canonical_action, params)

            is_valid, validation_msg = _validate_and_suggest(canonical_action, params)
            if not is_valid:
                return _err("Invalid parameters", validation_msg)

            if params.get("dry_run", True):
                logger.info(f"🔍 ENTERING DRY-RUN PATH for {canonical_action}")
                # Generate unique deployment ID
                deployment_id = str(uuid.uuid4())[:8]
                logger.info(f"Generated deployment ID: {deployment_id}")

                # TEMPORARY: Simple test to see if we get here
                test_result = _ok(
                    f"🔍 DRY RUN TEST - {canonical_action} (ID: {deployment_id})",
                    {
                        "deployment_id": deployment_id,
                        "action": canonical_action,
                        "parameters": params,
                        "status": "dry_run_test",
                        "message": "This is a test response to verify dry-run path works",
                    },
                )
                logger.info(f"🔍 RETURNING DRY-RUN TEST RESULT: {test_result}")
                return test_result
            else:
                logger.info(
                    f"🚀 ENTERING ACTUAL EXECUTION PATH for {canonical_action} (dry_run=False)"
                )

                # Get detailed deployment plan from Azure
                clients = await get_clients(params.get("subscription_id"))
                env = params.get("env", "dev")
                owner = params.get("owner", "devops-bot")
                extra_tags = params.get("tags", {})
                tags = standard_tags(extra_tags, owner, env)

                _, action_func = resolve_action(canonical_action)
                if not action_func:
                    return _err(
                        "Action not implemented", f"Action {canonical_action} is not available"
                    )

                # Build resource definition based on action and parameters
                resource_definition = _build_resource_definition(canonical_action, params)

                # Store pending deployment for confirmation
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

                try:
                    status, payload = await action_func(
                        clients=clients, tags=tags, dry_run=True, **params
                    )

                    if status == "plan":
                        detailed_plan = {
                            "deployment_id": deployment_id,
                            "deployment_plan": payload,
                            "action": canonical_action,
                            "parameters": params,
                            "confirmation_required": True,
                            "next_steps": [
                                " Review the deployment details above carefully",
                                " To proceed with actual deployment: 'deploy confirmed' or 'execute deployment'",
                                " To cancel: 'cancel deployment' or 'abort'",
                            ],
                            "estimated_resources": _extract_resource_summary(payload),
                            "environment": env,
                            "resource_group": params.get("resource_group"),
                            "location": params.get("location"),
                            "cost_warning": " This will create real Azure resources and may incur charges",
                        }
                        return _ok(
                            f" Deployment Plan Ready - {canonical_action} (ID: {deployment_id})",
                            detailed_plan,
                        )
                    else:
                        estimated_cost = _estimate_basic_cost(canonical_action, params)
                        detailed_preview = {
                            "deployment_id": deployment_id,
                            "action": canonical_action,
                            "parameters": params,
                            "confirmation_required": True,
                            "resource_details": _build_resource_preview(canonical_action, params),
                            "estimated_cost": estimated_cost,
                            "next_steps": [
                                " Review the resource configuration above",
                                " To proceed with actual deployment: 'deploy confirmed' or 'execute deployment'",
                                " To cancel: 'cancel deployment' or 'abort'",
                            ],
                            "environment": env,
                            "cost_warning": " This will create real Azure resources and may incur charges",
                        }
                        return _ok(
                            f" Deployment Preview Ready - {canonical_action} (ID: {deployment_id})",
                            detailed_preview,
                        )

                except Exception as e:
                    logger.warning(f"Failed to generate detailed plan for {canonical_action}: {e}")
                    estimated_cost = _estimate_basic_cost(canonical_action, params)
                    fallback_preview = {
                        "deployment_id": deployment_id,
                        "action": canonical_action,
                        "parameters": params,
                        "confirmation_required": True,
                        "resource_details": _build_resource_preview(canonical_action, params),
                        "estimated_cost": estimated_cost,
                        "planning_error": str(e),
                        "next_steps": [
                            " Detailed planning failed, showing basic configuration above",
                            " To proceed with deployment anyway: 'deploy confirmed'",
                            " To cancel: 'cancel deployment' or 'abort'",
                        ],
                        "environment": env,
                        "cost_warning": "⚠️ This will create real Azure resources and may incur charges",
                    }
                    return _ok(
                        f"🔍 Basic Preview Ready - {canonical_action} (ID: {deployment_id})",
                        fallback_preview,
                    )

            clients = await get_clients(params.get("subscription_id"))

            env = params.get("env", "dev")
            owner = params.get("owner", "devops-bot")
            extra_tags = params.get("tags", {})
            tags = standard_tags(extra_tags, owner, env)

            _, action_func = resolve_action(canonical_action)
            if not action_func:
                return _err("Action not implemented", f"Action {canonical_action} is not available")

            status, payload = await action_func(clients=clients, tags=tags, **params)

            if status == "plan":
                return _dry(f"{canonical_action} plan", payload)
            elif status in {"exists", "created", "updated", "ensured"}:
                return _ok(f"{canonical_action} {status}", payload)
            else:
                error_msg = (
                    payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
                )
                if "AccountKey" in error_msg:
                    error_msg = "[Account credentials redacted]"
                return _err(f"{canonical_action} failed", error_msg)

        except Exception as e:
            error_str = str(e)
            if "AccountKey" in error_str or "password" in error_str.lower():
                error_str = "[Sensitive information redacted]"
            return _err("Execution error", error_str)
