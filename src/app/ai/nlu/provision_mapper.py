from __future__ import annotations

import re

LOCATION_MAPPINGS = {
    "west europe": "westeurope",
    "westeurope": "westeurope",
    "north europe": "northeurope",
    "northeurope": "northeurope",
    "uk south": "uksouth",
    "uksouth": "uksouth",
    "east us": "eastus",
    "eastus": "eastus",
}

RESOURCE_TYPES = {
    "resource_group": ["resource group", "rg", "resourcegroup"],
    "storage_account": ["storage account", "storage", "blob"],
    "web_app": ["web app", "webapp", "app service", "website"],
    "vm": ["virtual machine", "vm"],
    "keyvault": ["key vault", "keyvault", "kv"],
    "aks": ["kubernetes", "aks", "k8s"],
    "acr": ["container registry", "acr", "docker registry"],
    "vnet": ["virtual network", "vnet"],
    "sql": ["sql server", "sql database", "database"],
}

ACTION_KEYWORDS = {
    "create": ["create", "make", "provision", "deploy", "setup", "add", "new"],
    "delete": ["delete", "remove", "destroy", "terminate"],
    "update": ["update", "modify", "change"],
}


def normalize_location(text: str) -> str | None:
    text_lower = text.lower().strip()
    for variant, normalized in LOCATION_MAPPINGS.items():
        if variant in text_lower:
            return normalized
    return None


def extract_resource_name(text: str, resource_type: str) -> str | None:
    patterns = [
        rf"{resource_type}\s+(?:named\s+|called\s+)?([a-z0-9][\w-]{{0,79}})",
        rf"(?:create|make|deploy)\s+(?:a\s+)?{resource_type}\s+([a-z0-9][\w-]{{0,79}})",
        rf"([a-z0-9][\w-]{{2,79}})\s+{resource_type}",
    ]

    for pattern in patterns:
        match = re.search(pattern, text.lower(), re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def detect_resource_type(text: str) -> str | None:
    text_lower = text.lower()
    for resource_key, variants in RESOURCE_TYPES.items():
        for variant in variants:
            if variant in text_lower:
                return resource_key
    return None


def detect_action(text: str) -> str:
    text_lower = text.lower()
    for action, keywords in ACTION_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return action
    return "create"


def extract_parameters(text: str) -> dict[str, object]:
    params: dict[str, object] = {}
    text_lower = text.lower()

    location = normalize_location(text_lower)
    if location:
        params["location"] = location

    resource_type = detect_resource_type(text_lower)
    if resource_type:
        name = extract_resource_name(text_lower, resource_type)
        if name:
            params["name"] = name
            if resource_type == "resource_group":
                params["resource_group"] = name

    sku_match = re.search(r"(?:sku|tier|size)\s+([a-z0-9_]+)", text_lower)
    if sku_match:
        params["sku"] = sku_match.group(1).upper()

    if "cool" in text_lower:
        params["access_tier"] = "Cool"
    elif "hot" in text_lower:
        params["access_tier"] = "Hot"

    return params


def maybe_map_provision(text: str) -> dict[str, object] | None:
    text = text.strip()
    if not text:
        return None

    resource_type = detect_resource_type(text)
    if not resource_type:
        return None

    params = extract_parameters(text)

    if not params.get("name") and not params.get("resource_group"):
        return None

    if not params.get("location"):
        params["location"] = "westeurope"

    if resource_type == "resource_group":
        if not params.get("resource_group"):
            params["resource_group"] = params.get("name", "")
        return {
            "tool": "azure_provision",
            "args": {
                "action": "create_rg",
                "resource_group": params["resource_group"],
                "location": params["location"],
                "dry_run": False,
            },
        }

    elif resource_type == "storage_account":
        return {
            "tool": "azure_provision",
            "args": {
                "action": "create_storage",
                "name": params.get("name"),
                "resource_group": params.get(
                    "resource_group", f"{params.get('name')}-rg"
                ),
                "location": params["location"],
                "sku": params.get("sku", "Standard_LRS"),
                "access_tier": params.get("access_tier", "Hot"),
                "dry_run": False,
            },
        }

    elif resource_type == "web_app":
        return {
            "tool": "azure_provision",
            "args": {
                "action": "create_webapp",
                "name": params.get("name"),
                "resource_group": params.get(
                    "resource_group", f"{params.get('name')}-rg"
                ),
                "location": params["location"],
                "plan": params.get("plan", f"{params.get('name')}-plan"),
                "dry_run": False,
            },
        }

    return None
