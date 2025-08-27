from __future__ import annotations

import json
from typing import Any


def generate_bicep_code(action: str, params: dict[str, Any]) -> str:
    resource_group = params.get("resource_group", "myapp-dev-rg")
    location = params.get("location", "westeurope")
    name = params.get("name", "myresource")
    environment = params.get("environment", "dev")

    if action in ["create_rg", "create_resource_group"]:
        return f"""// Azure Verified Module (AVM) - Resource Group
// Reference: https://aka.ms/avm/ptn/res/resource-group
targetScope = 'subscription'

@description('Name of the resource group')
param resourceGroupName string = '{resource_group}'

@description('Location for the resource group')
param location string = '{location}'

@description('Environment tag')
param environment string = '{environment}'

@description('Tags to be applied to the resource group')
param tags object = {{
  Environment: environment
  CreatedBy: 'Azure-AI-Assistant'
  Purpose: 'Infrastructure as Code'
  ManagedBy: 'Bicep-AVM'
}}

// Using AVM pattern for resource group deployment
resource resourceGroup 'Microsoft.Resources/resourceGroups@2023-07-01' = {{
  name: resourceGroupName
  location: location
  tags: tags
}}

@description('Resource group ID')
output resourceGroupId string = resourceGroup.id

@description('Resource group name')
output resourceGroupName string = resourceGroup.name

@description('Resource group location')
output location string = resourceGroup.location
"""

    if action in ["create_storage", "create_storage_account"]:
        sku = params.get("sku", "Standard_LRS")
        access_tier = params.get("access_tier", "Hot")
        return f"""// Azure Verified Module (AVM) - Storage Account
// Reference: https://aka.ms/avm/res/storage/storageaccount

@description('Name of the storage account')
param storageAccountName string = '{name}'

@description('Location for the storage account')
param location string = '{location}'

@description('Storage account SKU')
@allowed(['Standard_LRS', 'Standard_GRS', 'Standard_RAGRS', 'Standard_ZRS', 'Premium_LRS'])
param sku string = '{sku}'

@description('Access tier for blob storage')
@allowed(['Hot', 'Cool', 'Archive'])
param accessTier string = '{access_tier}'

@description('Environment tag')
param environment string = '{environment}'

@description('Tags to be applied to resources')
param tags object = {{
  Environment: environment
  CreatedBy: 'Azure-AI-Assistant'
  Purpose: 'Data Storage'
  ManagedBy: 'Bicep-AVM'
}}

// AVM-compliant Storage Account with security best practices
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
    allowSharedKeyAccess: true
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowCrossTenantReplication: false
    defaultToOAuthAuthentication: true
    networkAcls: {{
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }}
    encryption: {{
      services: {{
        blob: {{
          enabled: true
        }}
        file: {{
          enabled: true
        }}
      }}
      keySource: 'Microsoft.Storage'
    }}
  }}
  tags: tags
}}

@description('Storage account resource ID')
output storageAccountId string = storageAccount.id

@description('Storage account name')
output storageAccountName string = storageAccount.name

@description('Primary endpoints for the storage account')
output primaryEndpoints object = storageAccount.properties.primaryEndpoints

@description('Primary access key (use carefully)')
output primaryKey string = storageAccount.listKeys().keys[0].value
"""

    if action in ["create_webapp", "create_web_app"]:
        plan = params.get("plan", f"{name}-plan")
        runtime = params.get("runtime", "python|3.9")
        return f"""param webAppName string = '{name}'
param appServicePlanName string = '{plan}'
param location string = '{location}'
param runtime string = '{runtime}'

resource appServicePlan 'Microsoft.Web/serverfarms@2022-03-01' = {{
  name: appServicePlanName
  location: location
  sku: {{
    name: 'B1'
    tier: 'Basic'
  }}
  properties: {{
    reserved: true
  }}
  tags: {{
    Environment: '{params.get("environment", "dev")}'
    CreatedBy: 'Azure-AI-Bot'
  }}
}}

resource webApp 'Microsoft.Web/sites@2022-03-01' = {{
  name: webAppName
  location: location
  properties: {{
    serverFarmId: appServicePlan.id
    siteConfig: {{
      linuxFxVersion: runtime
      httpsOnly: true
      minTlsVersion: '1.2'
      alwaysOn: true
    }}
  }}
  tags: {{
    Environment: '{params.get("environment", "dev")}'
    CreatedBy: 'Azure-AI-Bot'
  }}
}}

output webAppId string = webApp.id
output webAppName string = webApp.name
output defaultHostName string = webApp.properties.defaultHostName
"""

    if action == "create_aks":
        node_count = params.get("node_count", 2)
        vm_size = params.get("vm_size", "Standard_D2s_v3")
        dns_prefix = params.get("dns_prefix", f"{name}-dns")
        return f"""param clusterName string = '{name}'
param location string = '{location}'
param dnsPrefix string = '{dns_prefix}'
param nodeCount int = {node_count}
param vmSize string = '{vm_size}'

resource aks 'Microsoft.ContainerService/managedClusters@2023-05-01' = {{
  name: clusterName
  location: location
  properties: {{
    dnsPrefix: dnsPrefix
    agentPoolProfiles: [
      {{
        name: 'agentpool'
        count: nodeCount
        vmSize: vmSize
        osType: 'Linux'
        mode: 'System'
      }}
    ]
    servicePrincipalProfile: {{
      clientId: 'msi'
    }}
  }}
  identity: {{
    type: 'SystemAssigned'
  }}
  tags: {{
    Environment: '{params.get("environment", "dev")}'
    CreatedBy: 'Azure-AI-Bot'
  }}
}}

output aksClusterId string = aks.id
output aksClusterName string = aks.name
output kubeconfigCommand string = 'az aks get-credentials --resource-group ${{resourceGroup().name}} --name ${{aks.name}}'
"""

    return f"""// Generic resource template for {action}
param resourceName string = '{name}'
param location string = '{location}'

// Action: {action}
// Parameters: {json.dumps(params, indent=2)}

output resourceName string = resourceName
output location string = location
"""
