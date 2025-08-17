from __future__ import annotations

from typing import Any

from azure.mgmt.eventhub import EventHubManagementClient
from azure.mgmt.eventhub.models import EHNamespace
from azure.mgmt.eventhub.models import Sku as EventHubSku

from ..clients import Clients


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
    client = EventHubManagementClient(clients.cred, clients.subscription_id)
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
