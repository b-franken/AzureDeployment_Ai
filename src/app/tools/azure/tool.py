from __future__ import annotations

import json
from typing import Any

from app.ai.nlu import parse_provision_request
from app.common.envs import ALLOWED_ENVS, normalize_env
from app.tools.base import Tool, ToolResult

from .actions.registry import action_names_with_aliases, resolve_action
from .clients import get_clients
from .tags import standard_tags
from .validators import validate_location, validate_name


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
            "location": {
                "type": "string",
                "enum": ["westeurope", "eastus", "northeurope", "uksouth"],
            },
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
                return _dry(
                    f"{canonical_action} preview",
                    {
                        "action": canonical_action,
                        "parameters": params,
                        "note": "Set dry_run=false to execute",
                    },
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
