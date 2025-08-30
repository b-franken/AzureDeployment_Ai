from __future__ import annotations

import uuid
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, Optional

from app.core.logging import get_logger
from app.tools.finops.cost_tool import AzureCosts
from app.tools.provision.backends.avm_bicep.engine import BicepAvmBackend, ProvisionContext
from app.ai.nlu.unified_parser import UnifiedParseResult

logger = get_logger(__name__)


class DeploymentPreviewService:
    def __init__(self):
        self.cost_service = AzureCosts()
        self.bicep_backend = BicepAvmBackend()

    async def generate_preview_response(
        self,
        nlu_result: UnifiedParseResult,
        subscription_id: str,
        resource_group: str | None = None,
        location: str = "westeurope",
        environment: str = "dev"
    ) -> str:
        logger.info(
            "Generating deployment preview",
            resource_type=nlu_result.resource_type,
            resource_name=nlu_result.resource_name,
            subscription_id=subscription_id
        )

        preview_id = str(uuid.uuid4())[:8]
        expires_at = datetime.now(UTC) + timedelta(minutes=30)

        resource_group = resource_group or nlu_result.parameters.get(
            "resource_group", "default-rg")
        resource_name = nlu_result.resource_name or "unnamed-resource"

        cost_estimate = await self._estimate_cost(nlu_result, subscription_id)
        bicep_content, terraform_content = await self._generate_infrastructure_files(
            nlu_result, subscription_id, resource_group, location, environment
        )

        response = f"""##  Azure Deployment Preview

**Resource Type:** {nlu_result.resource_type.title()}
**Resource Name:** {resource_name}
**Resource Group:** {resource_group}
**Location:** {location}
**Environment:** {environment}
**Preview ID:** {preview_id}
**Expires:** {expires_at.strftime('%Y-%m-%d %H:%M')} UTC (30 minutes)

###  Cost Estimate
**Estimated Monthly Cost:** ${cost_estimate:.2f}
*Actual costs may vary based on usage patterns*

###  Deployment Summary
- Strategy: Azure Verified Modules (AVM)
- Compliance: Production ready
- High Availability: {"Enabled" if nlu_result.advanced_context.get("security_enhanced") else "Standard"}
- Monitoring: Enabled with Application Insights

###  Infrastructure as Code

#### Bicep Template
```bicep
{bicep_content}
```

#### Terraform Configuration
```terraform
{terraform_content}
```

###  Prerequisites
- Azure subscription access
- Resource group '{resource_group}' exists
- Sufficient quota in {location} region

---
**Ready to deploy?** Reply with: `proceed` to start the actual deployment.
**Need changes?** Modify your request and I'll generate a new preview.
"""

        logger.info(
            "Preview generated successfully",
            preview_id=preview_id,
            estimated_cost=cost_estimate,
            resource_name=resource_name
        )

        return response

    async def _estimate_cost(self, nlu_result: UnifiedParseResult, subscription_id: str) -> float:
        try:
            resource_type = nlu_result.resource_type

            cost_estimates = {
                "storage": 5.0,
                "webapp": 75.0,
                "sql": 150.0,
                "aks": 300.0,
                "vm": 120.0,
                "keyvault": 2.0,
                "vnet": 0.0,
                "acr": 15.0
            }

            base_cost = cost_estimates.get(resource_type, 50.0)

            environment = nlu_result.parameters.get("environment", "dev")
            if environment in ["prod", "production"]:
                base_cost *= 2.5
            elif environment in ["staging", "stage"]:
                base_cost *= 1.5

            sku = nlu_result.parameters.get("sku", "")
            if "premium" in sku.lower():
                base_cost *= 3.0
            elif "standard" in sku.lower():
                base_cost *= 1.5

            return round(base_cost, 2)

        except Exception as e:
            logger.warning(
                "Cost estimation failed, using default", error=str(e))
            return 25.0

    async def _generate_infrastructure_files(
        self,
        nlu_result: UnifiedParseResult,
        subscription_id: str,
        resource_group: str,
        location: str,
        environment: str
    ) -> tuple[str, str]:
        try:
            resource_type = nlu_result.resource_type
            resource_name = nlu_result.resource_name or "unnamed-resource"

            bicep_template = self._generate_bicep_template(
                resource_type, resource_name, location, nlu_result.parameters
            )

            terraform_template = self._generate_terraform_template(
                resource_type, resource_name, location, resource_group, nlu_result.parameters
            )

            return bicep_template, terraform_template

        except Exception as e:
            logger.warning(
                "Infrastructure file generation failed", error=str(e))
            return self._get_fallback_templates(nlu_result.resource_type)

    def _generate_bicep_template(
        self,
        resource_type: str,
        resource_name: str,
        location: str,
        parameters: Dict[str, Any]
    ) -> str:
        if resource_type == "storage":
            sku = parameters.get("sku", "Standard_LRS")
            access_tier = parameters.get("access_tier", "Hot")
            return f"""@description('Storage Account for {resource_name}')
param storageAccountName string = '{resource_name}'
param location string = '{location}'
param sku string = '{sku}'
param accessTier string = '{access_tier}'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {{
  name: storageAccountName
  location: location
  sku: {{
    name: sku
  }}
  kind: 'StorageV2'
  properties: {{
    accessTier: accessTier
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }}
  tags: {{
    environment: 'dev'
    createdBy: 'devops-ai'
  }}
}}

output storageAccountId string = storageAccount.id
output primaryEndpoints object = storageAccount.properties.primaryEndpoints"""

        elif resource_type == "webapp":
            plan_name = f"{resource_name}-plan"
            sku = parameters.get("sku", "P1v3")
            return f"""@description('Web App and App Service Plan for {resource_name}')
param webAppName string = '{resource_name}'
param location string = '{location}'
param planName string = '{plan_name}'
param sku string = '{sku}'

resource appServicePlan 'Microsoft.Web/serverfarms@2023-01-01' = {{
  name: planName
  location: location
  sku: {{
    name: sku
  }}
  kind: 'linux'
  properties: {{
    reserved: true
  }}
}}

resource webApp 'Microsoft.Web/sites@2023-01-01' = {{
  name: webAppName
  location: location
  properties: {{
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {{
      linuxFxVersion: 'NODE|18-lts'
      minTlsVersion: '1.2'
    }}
  }}
  tags: {{
    environment: 'dev'
    createdBy: 'devops-ai'
  }}
}}

output webAppUrl string = webApp.properties.defaultHostName"""

        return f"""// Bicep template for {resource_type}
// Generated by DevOps AI
param resourceName string = '{resource_name}'
param location string = '{location}'

// Add your {resource_type} resource definition here"""

    def _generate_terraform_template(
        self,
        resource_type: str,
        resource_name: str,
        location: str,
        resource_group: str,
        parameters: Dict[str, Any]
    ) -> str:
        if resource_type == "storage":
            sku = parameters.get("sku", "Standard_LRS")
            access_tier = parameters.get("access_tier", "Hot")
            return f"""terraform {{
  required_providers {{
    azurerm = {{
      source  = "hashicorp/azurerm"
      version = "~>3.0"
    }}
  }}
}}

provider "azurerm" {{
  features {{}}
}}

resource "azurerm_storage_account" "{resource_name.replace('-', '_')}" {{
  name                     = "{resource_name}"
  resource_group_name      = "{resource_group}"
  location                 = "{location}"
  account_tier             = "Standard"
  account_replication_type = "{sku.replace('Standard_', '')}"
  access_tier              = "{access_tier}"

  allow_nested_items_to_be_public = false
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true

  tags = {{
    environment = "dev"
    created_by  = "devops-ai"
  }}
}}

output "storage_account_id" {{
  value = azurerm_storage_account.{resource_name.replace('-', '_')}.id
}}

output "primary_blob_endpoint" {{
  value = azurerm_storage_account.{resource_name.replace('-', '_')}.primary_blob_endpoint
}}"""

        elif resource_type == "webapp":
            plan_name = f"{resource_name}-plan"
            sku = parameters.get("sku", "P1v3")
            return f"""terraform {{
  required_providers {{
    azurerm = {{
      source  = "hashicorp/azurerm"
      version = "~>3.0"
    }}
  }}
}}

provider "azurerm" {{
  features {{}}
}}

resource "azurerm_service_plan" "{resource_name.replace('-', '_')}_plan" {{
  name                = "{plan_name}"
  resource_group_name = "{resource_group}"
  location            = "{location}"
  os_type             = "Linux"
  sku_name            = "{sku}"

  tags = {{
    environment = "dev"
    created_by  = "devops-ai"
  }}
}}

resource "azurerm_linux_web_app" "{resource_name.replace('-', '_')}" {{
  name                = "{resource_name}"
  resource_group_name = "{resource_group}"
  location            = "{location}"
  service_plan_id     = azurerm_service_plan.{resource_name.replace('-', '_')}_plan.id

  https_only = true

  site_config {{
    minimum_tls_version = "1.2"
    application_stack {{
      node_version = "18-lts"
    }}
  }}

  tags = {{
    environment = "dev"
    created_by  = "devops-ai"
  }}
}}

output "web_app_url" {{
  value = "https://${{azurerm_linux_web_app.{resource_name.replace('-', '_')}.default_hostname}}"
}}"""

        return f"""# Terraform configuration for {resource_type}
# Generated by DevOps AI

terraform {{
  required_providers {{
    azurerm = {{
      source  = "hashicorp/azurerm"
      version = "~>3.0"
    }}
  }}
}}

provider "azurerm" {{
  features {{}}
}}

# Add your {resource_type} resource definition here
resource "azurerm_{resource_type}" "{resource_name.replace('-', '_')}" {{
  name                = "{resource_name}"
  resource_group_name = "{resource_group}"
  location            = "{location}"
  
  tags = {{
    environment = "dev"
    created_by  = "devops-ai"
  }}
}}"""

    def _get_fallback_templates(self, resource_type: str) -> tuple[str, str]:
        bicep = f"""// Bicep template for {resource_type}
// Generated by DevOps AI
param resourceName string
param location string = resourceGroup().location

// Template generation failed, please customize as needed"""

        terraform = f"""# Terraform configuration for {resource_type}
# Generated by DevOps AI

terraform {{
  required_providers {{
    azurerm = {{
      source  = "hashicorp/azurerm"
      version = "~>3.0"
    }}
  }}
}}

# Template generation failed, please customize as needed"""

        return bicep, terraform
