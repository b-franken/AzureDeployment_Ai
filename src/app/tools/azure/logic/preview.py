from __future__ import annotations

from typing import Any


def get_resource_display_name(action: str) -> str:
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


def build_resource_preview(action: str, params: dict[str, Any]) -> dict[str, Any]:
    preview = {
        "Resource Type": get_resource_display_name(action),
        "Name": params.get("name", "Not specified"),
        "Location": params.get("location", "westeurope"),
        "Resource Group": params.get("resource_group", "Not specified"),
        "Environment": params.get("environment", "dev"),
    }
    if action in ["create_storage", "create_storage_account"]:
        preview.update(
            {
                "SKU/Performance": params.get("sku", "Standard_LRS"),
                "Access Tier": params.get("access_tier", "Hot"),
                "Redundancy": (
                    "Locally Redundant" if params.get("sku") == "Standard_LRS" else "Standard"
                ),
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


def build_resource_definition(action: str, params: dict[str, Any]) -> dict[str, Any]:
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


def extract_resource_summary(payload: dict) -> dict[str, str]:
    summary: dict[str, str] = {}
    if isinstance(payload, dict):
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
        if "cost_estimate" in payload:
            cost = payload["cost_estimate"]
            if isinstance(cost, dict):
                if "monthly_total" in cost:
                    summary["Estimated Monthly Cost"] = f"${cost['monthly_total']}"
                if "setup_cost" in cost:
                    summary["Setup Cost"] = f"${cost['setup_cost']}"
        if "dns_prefix" in payload:
            summary["DNS Prefix"] = payload["dns_prefix"]
        if "address_prefix" in payload:
            summary["Network Range"] = payload["address_prefix"]
        if "node_count" in payload:
            summary["Node Count"] = str(payload["node_count"])
    return summary


def estimate_basic_cost(action: str, params: dict[str, Any]) -> dict[str, str]:
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
            "note": "Basic tier about $5/month, Standard about $20/month",
        },
    }
    return cost_estimates.get(
        action,
        {
            "setup_cost": "$0.00",
            "monthly_estimate": "Variable",
            "note": "Use Azure pricing calculator for accurate estimates",
        },
    )
