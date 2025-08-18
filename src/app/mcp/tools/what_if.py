from __future__ import annotations

import asyncio
from typing import Any

from azure.identity import AzureCliCredential, ChainedTokenCredential, ManagedIdentityCredential
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.resource.resources.models import DeploymentMode  # type: ignore
from mcp.server.fastmcp import FastMCP


def _resource_client(subscription_id: str) -> ResourceManagementClient:
    cred = ChainedTokenCredential(ManagedIdentityCredential(), AzureCliCredential())
    return ResourceManagementClient(cred, subscription_id)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="azure_what_if",
        description="Preview changes (ARM/Bicep) with Azure what-if. Returns a clean diff summary.",
    )
    async def azure_what_if(
        subscription_id: str,
        resource_group: str,
        deployment_name: str,
        template: dict[str, Any] | None = None,
        template_link_uri: str | None = None,
        parameters: dict[str, Any] | None = None,
        mode: str = "Incremental",
    ) -> dict[str, Any]:
        """
        One of template or template_link_uri is required.
        parameters should be an Azure deployment-style dict: { paramName: { value: ... }, ... }
        """

        if not subscription_id or not resource_group or not deployment_name:
            raise ValueError("subscription_id, resource_group and deployment_name are required")

        if not template and not template_link_uri:
            raise ValueError("provide either 'template' or 'template_link_uri'")

        props: dict[str, Any] = {
            "mode": (
                DeploymentMode.incremental
                if mode.lower() == "incremental"
                else DeploymentMode.complete
            ),
        }
        if template:
            props["template"] = template
        if parameters:
            props["parameters"] = parameters
        if template_link_uri:
            props["templateLink"] = {"uri": template_link_uri}

        client = _resource_client(subscription_id)

        poller = await asyncio.to_thread(
            client.deployments.begin_what_if,
            resource_group,
            deployment_name,
            {"properties": props},
        )
        result = poller.result()

        changes = []
        for c in getattr(result, "changes", []) or []:
            changes.append(
                {
                    "changeType": getattr(c, "change_type", None),
                    "resourceId": getattr(c, "resource_id", None),
                    "before": getattr(c, "before", None),
                    "after": getattr(c, "after", None),
                    "delta": [
                        {
                            "path": getattr(d, "path", None),
                            "propertyChangeType": getattr(d, "property_change_type", None),
                            "before": getattr(d, "before", None),
                            "after": getattr(d, "after", None),
                        }
                        for d in (getattr(c, "delta", []) or [])
                    ],
                }
            )

        return {
            "status": "what_if_complete",
            "resourceGroup": resource_group,
            "deploymentName": deployment_name,
            "changes": changes,
        }
