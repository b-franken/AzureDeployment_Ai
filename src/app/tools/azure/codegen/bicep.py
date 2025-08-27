from __future__ import annotations

import json
from typing import Any


def generate_bicep_code(action: str, params: dict[str, Any]) -> str:
    resource_group = params.get("resource_group", "myapp-dev-rg")
    location = params.get("location", "westeurope")
    name = params.get("name", "myresource")

    if action in ["create_rg", "create_resource_group"]:
        return f"""targetScope = 'subscription'

param resourceGroupName string = '{resource_group}'
param location string = '{location}'

resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {{
  name: resourceGroupName
  location: location
  tags: {{
    Environment: '{params.get("environment", "dev")}'
    CreatedBy: 'Azure-AI-Bot'
  }}
}}

output resourceGroupId string = rg.id
output resourceGroupName string = rg.name
"""

    if action in ["create_storage", "create_storage_account"]:
        sku = params.get("sku", "Standard_LRS")
        access_tier = params.get("access_tier", "Hot")
        return f"""param storageAccountName string = '{name}'
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
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
  }}
  tags: {{
    Environment: '{params.get("environment", "dev")}'
    CreatedBy: 'Azure-AI-Bot'
  }}
}}

output storageAccountId string = storageAccount.id
output storageAccountName string = storageAccount.name
output primaryEndpoints object = storageAccount.properties.primaryEndpoints
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
