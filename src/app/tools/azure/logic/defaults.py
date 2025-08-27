from __future__ import annotations

from typing import Any


def apply_intelligent_defaults(action: str, params: dict[str, Any]) -> None:
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
