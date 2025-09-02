from __future__ import annotations

import asyncio
from typing import Any

from azure.identity import AzureCliCredential, ChainedTokenCredential, ManagedIdentityCredential
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.resource.resources.models import DeploymentMode, DeploymentWhatIf
from mcp.server.fastmcp import FastMCP

from app.core.logging import get_logger

logger = get_logger(__name__)


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

        # Build deployment properties with correct typing
        deployment_mode = (
            DeploymentMode.incremental if mode.lower() == "incremental" else DeploymentMode.complete
        )

        # Create properties dict with proper types for DeploymentWhatIfProperties
        properties_dict: dict[str, Any] = {
            "mode": deployment_mode,
        }

        if template:
            properties_dict["template"] = template
        if parameters:
            properties_dict["parameters"] = parameters
        if template_link_uri:
            properties_dict["template_link"] = {"uri": template_link_uri}

        client = _resource_client(subscription_id)

        # Create DeploymentWhatIf with properties parameter
        # Azure SDK expects a properties object, not individual parameters
        try:
            from azure.mgmt.resource.resources.models import DeploymentWhatIfProperties

            mode_str = (
                deployment_mode.value if hasattr(deployment_mode, "value") else str(deployment_mode)
            )
            logger.debug(
                "Creating DeploymentWhatIfProperties",
                mode=mode_str,
                has_template=template is not None,
                has_parameters=parameters is not None,
                has_template_link=template_link_uri is not None,
            )

            deployment_properties = DeploymentWhatIfProperties(**properties_dict)
            deployment_what_if = DeploymentWhatIf(properties=deployment_properties)

            logger.info(
                "DeploymentWhatIf object created successfully",
                resource_group=resource_group,
                deployment_name=deployment_name,
            )

        except ImportError as ie:
            logger.warning(
                "DeploymentWhatIfProperties not available, using fallback", error=str(ie)
            )
            # Fallback: This may fail if Azure SDK expects specific types
            # but we need to handle cases where DeploymentWhatIfProperties is not available
            try:
                # Type ignore is necessary here because we're falling back to a
                # less type-safe approach when DeploymentWhatIfProperties is not available
                deployment_what_if = DeploymentWhatIf(properties=properties_dict)  # type: ignore[arg-type]
            except Exception as fallback_error:
                logger.error(
                    "Both primary and fallback methods failed",
                    primary_error=str(ie),
                    fallback_error=str(fallback_error),
                )
                raise ValueError(
                    f"Unable to create DeploymentWhatIf object. "
                    f"Primary error: {str(ie)}, Fallback error: {str(fallback_error)}"
                ) from fallback_error
        except Exception as e:
            logger.error(
                "Failed to create DeploymentWhatIf object",
                error=str(e),
                error_type=type(e).__name__,
                properties_keys=list(properties_dict.keys()),
            )
            raise ValueError(f"Failed to create deployment what-if object: {str(e)}") from e

        poller = await asyncio.to_thread(
            client.deployments.begin_what_if,
            resource_group,
            deployment_name,
            deployment_what_if,
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
