from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastmcp import Context
from azure.core.exceptions import AzureError

# These clients are optional; we guard imports/usages so the server still boots
try:
    from azure.mgmt.compute import ComputeManagementClient
except Exception:  # pragma: no cover - best effort import
    ComputeManagementClient = None  # type: ignore[assignment]

try:
    from azure.mgmt.network import NetworkManagementClient
except Exception:  # pragma: no cover - best effort import
    NetworkManagementClient = None  # type: ignore[assignment]

from app.core.azure_auth import build_credential

logger = logging.getLogger("app.mcp.extensions")


def _safe_usage_record(item: Any) -> dict[str, Any]:
    """Normalize Azure usage/quota items to a consistent dict."""
    try:
        name = getattr(getattr(item, "name", None), "value", None) or getattr(
            getattr(item, "name", None), "localized_value", None
        )
        # Azure models differ slightly between services; try common attrs
        return {
            "name": name or getattr(item, "name", None),
            "current_value": getattr(item, "current_value", None)
            or getattr(item, "current", None),
            "limit": getattr(item, "limit", None) or getattr(item, "max_value", None),
            "unit": getattr(item, "unit", None),
        }
    except Exception:  # extremely defensive – never crash quota endpoint
        logger.exception("Failed to normalize quota usage item", extra={
                         "event": "quota_item_normalize_error"})
        return {"name": None, "current_value": None, "limit": None, "unit": None}


def register_extensions(server: Any) -> None:
    """
    Register extra MCP resources that aren't part of the core server.

    NOTE: For FastMCP resources, `context` MUST be the first parameter. If it's
    not first, FastMCP will treat it as a required URI parameter and raise:
    "Required function arguments {..., 'context'} must be a subset of the URI parameters {...}".
    """
    mcp = server.mcp

    @mcp.resource("azure://quotas/{subscription_id}/{location}")
    async def get_quotas(context: Context, subscription_id: str, location: str) -> dict[str, Any]:
        """
        Return compute/network quota information for a subscription/location.

        URI params:
          - subscription_id
          - location

        Returns a payload shaped like:
        {
          "subscription_id": "...",
          "location": "westeurope",
          "services": {
            "compute": [ {name, current_value, limit, unit}, ... ],
            "network": [ {name, current_value, limit, unit}, ... ]
          }
        }
        """
        logger.info(
            "Fetching Azure quotas",
            extra={
                "event": "azure_quotas_fetch",
                "subscription_id": subscription_id,
                "location": location,
            },
        )

        cred = None
        try:
            cred = build_credential()
        except Exception as e:
            logger.exception("Failed to build Azure credential",
                             extra={"event": "azure_cred_error"})
            return {
                "subscription_id": subscription_id,
                "location": location,
                "services": {},
                "error": f"credential_error:{e}",
            }

        services: dict[str, list[dict[str, Any]]] = {}

        # ---- Compute quotas ----
        try:
            compute_items: list[dict[str, Any]] = []
            if ComputeManagementClient is not None:
                comp_client = ComputeManagementClient(cred, subscription_id)
                usages = await asyncio.to_thread(lambda: list(comp_client.usage.list(location)))
                compute_items = [_safe_usage_record(u) for u in usages]
            else:
                logger.warning(
                    "ComputeManagementClient unavailable; skipping compute quotas",
                    extra={"event": "compute_client_missing"},
                )
            services["compute"] = compute_items
        except AzureError as e:
            logger.error(
                "Azure error while fetching compute quotas",
                extra={"event": "compute_quotas_azure_error",
                       "details": str(e)},
            )
            services["compute"] = []
        except Exception as e:  # pragma: no cover
            logger.exception(
                "Unexpected error while fetching compute quotas",
                extra={"event": "compute_quotas_unexpected_error"},
            )
            services["compute"] = []
            # Keep response resilient – don't fail the whole resource
            # but surface a hint to callers.
            services.setdefault("_errors", []).append(f"compute:{e}")

        # ---- Network quotas ----
        try:
            network_items: list[dict[str, Any]] = []
            if NetworkManagementClient is not None:
                net_client = NetworkManagementClient(cred, subscription_id)
                usages = await asyncio.to_thread(lambda: list(net_client.usages.list(location)))
                network_items = [_safe_usage_record(u) for u in usages]
            else:
                logger.warning(
                    "NetworkManagementClient unavailable; skipping network quotas",
                    extra={"event": "network_client_missing"},
                )
            services["network"] = network_items
        except AzureError as e:
            logger.error(
                "Azure error while fetching network quotas",
                extra={"event": "network_quotas_azure_error",
                       "details": str(e)},
            )
            services["network"] = []
        except Exception as e:  # pragma: no cover
            logger.exception(
                "Unexpected error while fetching network quotas",
                extra={"event": "network_quotas_unexpected_error"},
            )
            services["network"] = []
            services.setdefault("_errors", []).append(f"network:{e}")

        payload = {
            "subscription_id": subscription_id,
            "location": location,
            "services": services,
        }
        logger.info(
            "Azure quotas fetched",
            extra={
                "event": "azure_quotas_success",
                "subscription_id": subscription_id,
                "location": location,
                "compute_items": len(services.get("compute", [])),
                "network_items": len(services.get("network", [])),
            },
        )
        return payload


__all__ = ["register_extensions"]
