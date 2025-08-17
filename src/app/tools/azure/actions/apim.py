from __future__ import annotations

from typing import Any

from azure.mgmt.apimanagement import ApiManagementClient
from azure.mgmt.apimanagement.models import (
    ApiManagementServiceResource,
    ApiManagementServiceSkuProperties,
)

from ..clients import Clients


async def create_apim(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    name: str,
    sku: str = "Developer",
    capacity: int = 1,
    publisher_email: str = "admin@contoso.com",
    publisher_name: str = "Contoso",
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
            "sku": {"name": sku, "capacity": capacity},
            "publisher_email": publisher_email,
            "publisher_name": publisher_name,
            "tags": tags or {},
        }
    client = ApiManagementClient(clients.cred, clients.subscription_id)
    sku_props = ApiManagementServiceSkuProperties(name=sku, capacity=capacity)
    params = ApiManagementServiceResource(
        location=location,
        sku=sku_props,
        publisher_email=publisher_email,
        publisher_name=publisher_name,
        tags=tags or {},
    )
    poller = await clients.run(
        client.api_management_service.begin_create_or_update,
        resource_group,
        name,
        params,
    )
    result = await clients.run(poller.result)
    return "created", result.as_dict()
