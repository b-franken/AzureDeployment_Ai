from __future__ import annotations

import asyncio
import importlib
import time
from typing import Any, TypedDict

from azure.core.exceptions import AzureError
from fastmcp import Context

from app.core.azure_auth import build_credential
from app.core.logging import get_logger

logger = get_logger(__name__)


class UsageRecord(TypedDict, total=False):
    name: str | None
    current_value: int | None
    limit: int | None
    unit: str | None


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:  # noqa: BLE001
        return None


def _safe_usage_record(item: Any) -> UsageRecord:
    try:
        name_obj = getattr(item, "name", None)
        name_val = getattr(name_obj, "value", None) if name_obj is not None else None
        if not name_val and name_obj is not None:
            name_val = getattr(name_obj, "localized_value", None)
        current_value = getattr(item, "current_value", None)
        if current_value is None:
            current_value = getattr(item, "current", None)
        limit_val = getattr(item, "limit", None)
        if limit_val is None:
            limit_val = getattr(item, "max_value", None)
        unit_val = getattr(item, "unit", None)
        return {
            "name": name_val or getattr(item, "name", None),
            "current_value": _coerce_int(current_value),
            "limit": _coerce_int(limit_val),
            "unit": str(unit_val) if unit_val is not None else None,
        }
    except Exception:
        logger.exception(
            "quota_item.normalize_error", extra={"event": "azure_quotas.normalize_error"}
        )
        return {"name": None, "current_value": None, "limit": None, "unit": None}


def _get_sync_client(
    module_name: str, class_name: str, cred: Any, subscription_id: str
) -> Any | None:
    try:
        mod = importlib.import_module(module_name)
        cls = getattr(mod, class_name)
        return cls(cred, subscription_id)
    except ModuleNotFoundError:
        logger.warning(
            "azure_sdk.module_missing",
            extra={
                "event": "azure_quotas.module_missing",
                "module": module_name,
                "class": class_name,
            },
        )
        return None
    except Exception as exc:
        logger.exception(
            "azure_sdk.client_init_error",
            extra={
                "event": "azure_quotas.client_init_error",
                "module": module_name,
                "class": class_name,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return None


async def _fetch_compute_usages(
    cred: Any, subscription_id: str, location: str
) -> list[UsageRecord]:
    t0 = time.perf_counter()
    try:
        client = _get_sync_client(
            "azure.mgmt.compute", "ComputeManagementClient", cred, subscription_id
        )
        if client is None:
            return []
        usages = await asyncio.to_thread(lambda: list(client.usage.list(location)))
        items = [_safe_usage_record(u) for u in usages]
        logger.debug(
            "azure_quotas.compute.done",
            extra={
                "event": "azure_quotas.compute_success",
                "count": len(items),
                "duration_ms": (time.perf_counter() - t0) * 1000.0,
            },
        )
        return items
    except AzureError as exc:
        logger.error(
            "azure_quotas.compute.azure_error",
            extra={
                "event": "azure_quotas.compute_error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
            exc_info=True,
        )
        return []
    except Exception as exc:
        logger.exception(
            "azure_quotas.compute.unexpected_error",
            extra={
                "event": "azure_quotas.compute_unexpected_error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return []


async def _fetch_network_usages(
    cred: Any, subscription_id: str, location: str
) -> list[UsageRecord]:
    t0 = time.perf_counter()
    try:
        client = _get_sync_client(
            "azure.mgmt.network", "NetworkManagementClient", cred, subscription_id
        )
        if client is None:
            return []
        usages = await asyncio.to_thread(lambda: list(client.usages.list(location)))
        items = [_safe_usage_record(u) for u in usages]
        logger.debug(
            "azure_quotas.network.done",
            extra={
                "event": "azure_quotas.network_success",
                "count": len(items),
                "duration_ms": (time.perf_counter() - t0) * 1000.0,
            },
        )
        return items
    except AzureError as exc:
        logger.error(
            "azure_quotas.network.azure_error",
            extra={
                "event": "azure_quotas.network_error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
            exc_info=True,
        )
        return []
    except Exception as exc:
        logger.exception(
            "azure_quotas.network.unexpected_error",
            extra={
                "event": "azure_quotas.network_unexpected_error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return []


def register_extensions(server: Any) -> None:
    mcp = server.mcp

    @mcp.resource("azure://quotas/{subscription_id}/{location}")  # type: ignore[misc]
    async def get_quotas(context: Context, subscription_id: str, location: str) -> dict[str, Any]:
        start = time.perf_counter()
        logger.info(
            "azure_quotas.fetch.start",
            extra={
                "event": "azure_quotas.fetch_start",
                "subscription_id": subscription_id,
                "location": location,
            },
        )
        errors: list[str] = []
        try:
            cred = build_credential()
        except Exception as exc:
            logger.exception(
                "azure_quotas.credential_error",
                extra={
                    "event": "azure_quotas.credential_error",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            return {
                "subscription_id": subscription_id,
                "location": location,
                "services": {"compute": [], "network": []},
                "errors": [f"credential_error:{exc}"],
            }

        compute_items = await _fetch_compute_usages(cred, subscription_id, location)
        network_items = await _fetch_network_usages(cred, subscription_id, location)

        payload: dict[str, Any] = {
            "subscription_id": subscription_id,
            "location": location,
            "services": {"compute": compute_items, "network": network_items},
            "errors": errors,
        }

        logger.info(
            "azure_quotas.fetch.end",
            extra={
                "event": "azure_quotas.fetch_success",
                "subscription_id": subscription_id,
                "location": location,
                "compute_items": len(compute_items),
                "network_items": len(network_items),
                "duration_ms": (time.perf_counter() - start) * 1000.0,
            },
        )
        return payload


__all__ = ["register_extensions"]
