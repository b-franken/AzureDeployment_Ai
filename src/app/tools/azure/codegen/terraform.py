from __future__ import annotations

import json
from typing import Any


def generate_terraform_code(action: str, params: dict[str, Any]) -> str:
    resource_group = params.get("resource_group", "myapp-dev-rg")
    location = params.get("location", "westeurope")
    name = params.get("name", "myresource")

    terraform_config = """terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~>3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

"""

    if action in ["create_rg", "create_resource_group"]:
        terraform_config += f"""resource "azurerm_resource_group" "main" {{
  name     = "{resource_group}"
  location = "{location}"

  tags = {{
    Environment = "{params.get("environment", "dev")}"
    CreatedBy   = "Azure-AI-Bot"
  }}
}}

output "resource_group_id" {{
  value = azurerm_resource_group.main.id
}}

output "resource_group_name" {{
  value = azurerm_resource_group.main.name
}}
"""

    elif action in ["create_storage", "create_storage_account"]:
        sku = params.get("sku", "Standard_LRS")
        access_tier = params.get("access_tier", "Hot")
        repl = sku.split("_")[1] if "_" in sku else "LRS"
        terraform_config += f"""resource "azurerm_storage_account" "main" {{
  name                     = "{name}"
  resource_group_name      = "{resource_group}"
  location                 = "{location}"
  account_tier             = "Standard"
  account_replication_type = "{repl}"
  access_tier              = "{access_tier}"
  enable_https_traffic_only = true
  min_tls_version          = "TLS1_2"
  allow_nested_items_to_be_public = false

  tags = {{
    Environment = "{params.get("environment", "dev")}"
    CreatedBy   = "Azure-AI-Bot"
  }}
}}

output "storage_account_id" {{
  value = azurerm_storage_account.main.id
}}

output "storage_account_name" {{
  value = azurerm_storage_account.main.name
}}

output "primary_blob_endpoint" {{
  value = azurerm_storage_account.main.primary_blob_endpoint
}}
"""

    elif action in ["create_webapp", "create_web_app"]:
        plan = params.get("plan", f"{name}-plan")
        runtime = params.get("runtime", "python|3.9")
        py = runtime.split("|")[1] if "|" in runtime else "3.9"
        terraform_config += f"""resource "azurerm_service_plan" "main" {{
  name                = "{plan}"
  resource_group_name = "{resource_group}"
  location            = "{location}"
  os_type             = "Linux"
  sku_name            = "B1"

  tags = {{
    Environment = "{params.get("environment", "dev")}"
    CreatedBy   = "Azure-AI-Bot"
  }}
}}

resource "azurerm_linux_web_app" "main" {{
  name                = "{name}"
  resource_group_name = "{resource_group}"
  location            = "{location}"
  service_plan_id     = azurerm_service_plan.main.id

  site_config {{
    application_stack {{
      python_version = "{py}"
    }}
    always_on = true
    https_only = true
    minimum_tls_version = "1.2"
  }}

  tags = {{
    Environment = "{params.get("environment", "dev")}"
    CreatedBy   = "Azure-AI-Bot"
  }}
}}

output "web_app_id" {{
  value = azurerm_linux_web_app.main.id
}}

output "web_app_name" {{
  value = azurerm_linux_web_app.main.name
}}

output "default_hostname" {{
  value = azurerm_linux_web_app.main.default_hostname
}}
"""

    elif action == "create_aks":
        node_count = params.get("node_count", 2)
        vm_size = params.get("vm_size", "Standard_D2s_v3")
        dns_prefix = params.get("dns_prefix", f"{name}-dns")
        terraform_config += f"""resource "azurerm_kubernetes_cluster" "main" {{
  name                = "{name}"
  location            = "{location}"
  resource_group_name = "{resource_group}"
  dns_prefix          = "{dns_prefix}"

  default_node_pool {{
    name       = "default"
    node_count = {node_count}
    vm_size    = "{vm_size}"
  }}

  identity {{
    type = "SystemAssigned"
  }}

  tags = {{
    Environment = "{params.get("environment", "dev")}"
    CreatedBy   = "Azure-AI-Bot"
  }}
}}

output "kube_config" {{
  value = azurerm_kubernetes_cluster.main.kube_config_raw
  sensitive = true
}}

output "cluster_id" {{
  value = azurerm_kubernetes_cluster.main.id
}}

output "cluster_name" {{
  value = azurerm_kubernetes_cluster.main.name
}}
"""

    else:
        terraform_config += f"""# Generic resource template for {action}
# Resource name: {name}
# Location: {location}
# Parameters: {json.dumps(params, indent=2)}

# Add specific resource configuration here
"""

    return terraform_config
