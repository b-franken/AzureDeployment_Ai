from __future__ import annotations

import json
from typing import Any

from app.tools.azure.deployment_phases import DeploymentState


class DeploymentOutputFormatter:
    """Professional output formatting for Azure deployments without emojis."""
    
    @staticmethod
    def format_preview_output(
        state: DeploymentState,
        resource_type: str,
        resource_name: str,
    ) -> str:
        """Format deployment preview output for user confirmation."""
        monthly_cost = state.cost_estimate.get("monthly_estimate", 0.0)
        
        sections = [
            "## Azure Deployment Preview",
            "",
            "**Resource Summary:**",
            f"- Resource Type: {resource_type.title()}",
            f"- Resource Name: {resource_name}",
            f"- Resource Group: {state.resource_group}",
            f"- Location: {state.location}",
            f"- Environment: dev",
            f"- Estimated Monthly Cost: ${monthly_cost:.2f} USD",
            "",
            "## Bicep Template Preview",
            "```bicep",
            state.bicep_template,
            "```",
            "",
            "## Equivalent Terraform Configuration",
            "```hcl",
            state.terraform_config,
            "```",
            "",
        ]
        
        if state.what_if_analysis:
            sections.extend([
                "## What-If Analysis",
                "```",
                state.what_if_analysis,
                "```",
                "",
            ])
        
        if state.cost_estimate:
            sections.extend([
                "## Cost Breakdown",
                "```json",
                json.dumps(state.cost_estimate, indent=2),
                "```",
                "",
            ])
        
        sections.extend([
            "## Next Steps",
            "Review the templates and cost analysis above.",
            "",
            "**To proceed with deployment, reply with: `proceed`**",
            "",
            f"**Preview ID:** {state.deployment_id}",
            f"**Expires:** {state.expires_at.strftime('%H:%M:%S')} (30 minutes)",
        ])
        
        return "\n".join(sections)
    
    @staticmethod
    def format_deployment_output(
        deployment_result: dict[str, Any],
        bicep_template: str,
        terraform_config: str,
        duration: str,
        deployment_id: str,
        resource_group: str,
        location: str,
    ) -> str:
        """Format successful deployment output."""
        outputs = deployment_result.get("outputs", {})
        
        sections = [
            "## Azure Deployment Completed",
            "",
            "**Deployment Status:** Succeeded",
            f"**Resource Group:** {resource_group}",
            f"**Location:** {location}",
            f"**Duration:** {duration}",
            f"**Deployment ID:** {deployment_id}",
            "",
            "## Deployed Resources",
            "```json",
            json.dumps(outputs, indent=2),
            "```",
            "",
            "## Bicep Template Used",
            "```bicep",
            bicep_template,
            "```",
            "",
            "## Terraform Configuration for Deployed Resources",
            "```hcl",
            terraform_config,
            "```",
            "",
            "## Next Steps",
            "1. Verify deployment in Azure Portal",
            "2. Test resource functionality",
            "3. Configure monitoring and alerting",
            "4. Document configuration for team reference",
            "",
            "**Note:** These templates represent the actual deployed infrastructure.",
        ]
        
        return "\n".join(sections)
    
    @staticmethod
    def format_deployment_error(
        error_message: str,
        deployment_id: str | None = None,
        resource_group: str | None = None,
    ) -> str:
        """Format deployment error output."""
        sections = [
            "## Azure Deployment Failed",
            "",
            f"**Error:** {error_message}",
        ]
        
        if deployment_id:
            sections.append(f"**Deployment ID:** {deployment_id}")
        if resource_group:
            sections.append(f"**Resource Group:** {resource_group}")
            
        sections.extend([
            "",
            "## Troubleshooting Steps",
            "1. Check Azure Portal for detailed error information",
            "2. Verify subscription permissions and quotas",
            "3. Review resource naming conventions",
            "4. Check for resource conflicts or dependencies",
            "",
            "**Need help?** Review the error details above or contact your Azure administrator.",
        ])
        
        return "\n".join(sections)
    
    @staticmethod
    def format_state_not_found_error(user_id: str) -> str:
        """Format error when deployment state is not found or expired."""
        return """## Deployment State Not Found

**Error:** No active deployment preview found.

**Possible causes:**
- Preview session expired (30 minutes)
- No recent deployment preview generated
- Session was cleared

**Next steps:**
1. Generate a new deployment preview
2. Confirm deployment within 30 minutes of preview

**Example:** Create a new deployment request like "create storage account mystore in resource group rg-prod"
"""
    
    @staticmethod
    def format_confirmation_timeout_error(deployment_id: str) -> str:
        """Format error when user tries to confirm expired deployment."""
        return f"""## Deployment Preview Expired

**Error:** Deployment preview {deployment_id[:8]} has expired.

**Reason:** Preview sessions expire after 30 minutes for security.

**Next steps:**
1. Generate a new deployment preview
2. Confirm deployment within 30 minutes

**Security Note:** This timeout prevents unauthorized deployments from stale sessions.
"""


class TerraformGenerator:
    """Generate Terraform configurations from deployed Azure resources."""
    
    @staticmethod
    def generate_from_storage_account(
        storage_name: str,
        resource_group: str,
        location: str,
        outputs: dict[str, Any],
    ) -> str:
        """Generate Terraform for deployed storage account."""
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

# Storage account deployed via AVM Bicep
resource "azurerm_storage_account" "deployed" {{
  name                     = "{storage_name}"
  resource_group_name      = "{resource_group}"
  location                 = "{location}"
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  
  # Security settings matching AVM deployment
  public_network_access_enabled   = true
  allow_nested_items_to_be_public = false
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true

  tags = {{
    Environment = "dev"
    ManagedBy   = "AVM-Bicep"
    CreatedBy   = "IntelligentAzureProvision"
  }}
}}

# Outputs matching deployed resource
output "storage_account_id" {{
  value       = azurerm_storage_account.deployed.id
  description = "The ID of the deployed storage account"
}}

output "storage_account_name" {{
  value       = azurerm_storage_account.deployed.name
  description = "The name of the deployed storage account"
}}

output "primary_blob_endpoint" {{
  value       = azurerm_storage_account.deployed.primary_blob_endpoint
  description = "The primary blob endpoint"
}}"""

    @staticmethod
    def generate_generic(
        resource_type: str,
        resource_name: str,
        resource_group: str,
        location: str,
        resource_id: str | None = None,
    ) -> str:
        """Generate generic Terraform template for unsupported resource types."""
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

# {resource_type.title()} resource deployed via AVM Bicep
# Resource Name: {resource_name}
# Resource Group: {resource_group}
# Location: {location}
# Resource ID: {resource_id or 'Not available'}

# Note: Terraform configuration for {resource_type} requires
# resource-specific implementation based on deployed properties.
# This template provides the basic structure for infrastructure as code.

data "azurerm_resource_group" "deployed" {{
  name = "{resource_group}"
}}

output "resource_group_id" {{
  value       = data.azurerm_resource_group.deployed.id
  description = "Resource group containing the deployed {resource_type}"
}}"""