from __future__ import annotations

from typing import Any

from azure.core.exceptions import HttpResponseError
from azure.mgmt.eventhub import EventHubManagementClient
from azure.mgmt.eventhub.models import EHNamespace
from azure.mgmt.eventhub.models import Sku as EventHubSku

from app.core.logging import get_logger

from ..clients import Clients
from ..utils.credentials import ensure_sync_credential

logger = get_logger(__name__)


async def create_eventhub(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    name: str,
    tier: str = "Standard",
    capacity: int = 1,
    auto_inflate: bool = True,
    max_throughput: int = 10,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
    **_: Any,
) -> tuple[str, object]:
    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "location": location,
            "sku": {"name": tier, "tier": tier, "capacity": capacity},
            "is_auto_inflate_enabled": bool(auto_inflate),
            "maximum_throughput_units": max_throughput,
            "tags": tags or {},
        }

    sync_cred = ensure_sync_credential(clients.cred)
    client = EventHubManagementClient(sync_cred, clients.subscription_id)
    try:
        try:
            existing = await clients.run(client.namespaces.get, resource_group, name)
            if existing and not force:
                return "exists", existing.as_dict()
        except HttpResponseError as exc:
            if exc.status_code != 404:
                logger.error("Event Hub namespace retrieval failed: %s", exc.message)
                return "error", {"code": exc.status_code, "message": exc.message}

        sku = EventHubSku(name=tier, tier=tier, capacity=capacity)
        params = EHNamespace(
            location=location,
            sku=sku,
            is_auto_inflate_enabled=bool(auto_inflate),
            maximum_throughput_units=max_throughput,
            tags=tags or {},
        )

        poller = await clients.run(
            client.namespaces.begin_create_or_update,
            resource_group,
            name,
            params,
        )
        result = await clients.run(poller.result)
        return "created", result.as_dict()
    except HttpResponseError as exc:
        logger.error("Event Hub namespace create_or_update failed: %s", exc.message)
        return "error", {"code": exc.status_code, "message": exc.message}
    except Exception as exc:
        logger.exception("Unexpected error while creating Event Hub namespace")
        return "error", {"message": str(exc)}
    finally:
        close = getattr(sync_cred, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                logger.debug("Credential close raised but was ignored")
