from __future__ import annotations

from typing import Any

from ..validators import validate_location, validate_name


def validate_and_suggest(action: str, params: dict[str, Any]) -> tuple[bool, str]:
    required_by_action = {
        "create_rg": ["resource_group", "location"],
        "create_resource_group": ["resource_group", "location"],
        "create_storage": ["resource_group", "location", "name"],
        "create_storage_account": ["resource_group", "location", "name"],
        "create_webapp": ["resource_group", "name", "plan"],
        "create_web_app": ["resource_group", "name", "plan"],
        "create_vm": ["resource_group", "location", "name", "vm_size", "admin_username"],
        "create_keyvault": ["resource_group", "location", "vault_name", "tenant_id"],
        "create_aks": ["resource_group", "location", "name", "dns_prefix"],
        "create_acr": ["resource_group", "location", "name"],
        "create_sql": ["resource_group", "location", "server_name", "sql_admin_user", "sql_admin_password"],
        "create_vnet": ["resource_group", "location", "name", "address_prefix"],
    }

    if action not in required_by_action:
        return True, ""

    missing = [p for p in required_by_action[action]
               if p not in params or not params[p]]
    if missing:
        suggestions = []
        for param in missing:
            if param == "location":
                suggestions.append(
                    "location: westeurope, eastus, northeurope, uksouth")
            elif param == "resource_group":
                suggestions.append("resource_group: your-project-dev-rg")
            elif param == "name":
                suggestions.append("name: unique name for your resource")
            else:
                suggestions.append(f"{param}: required parameter")
        return False, f"Missing: {', '.join(missing)}. Suggestions: {'; '.join(suggestions)}"

    if params.get("location") and not validate_location(params["location"]):
        return False, "Invalid location. Use: westeurope, eastus, northeurope, or uksouth"

    validation_rules = {
        "storage": ("name", 3, 24, "lowercase letters and numbers only"),
        "webapp": ("name", 2, 60, "letters, numbers, and hyphens"),
        "acr": ("name", 5, 50, "letters and numbers only"),
        "sql_server": ("server_name", 1, 63, "letters, numbers, and hyphens"),
    }

    for resource_type, (field, min_len, max_len, desc) in validation_rules.items():
        if action.endswith(resource_type) and field in params:
            if not validate_name(resource_type, params[field]):
                return False, f"Invalid {field}: must be {min_len}-{max_len} characters, {desc}"

    return True, ""
