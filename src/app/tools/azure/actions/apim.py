from __future__ import annotations

from typing import Any

from azure.core.exceptions import HttpResponseError
from azure.mgmt.apimanagement import ApiManagementClient
from azure.mgmt.apimanagement.models import (
    ApiManagementServiceResource,
    ApiManagementServiceSkuProperties,
)

from app.core.logging import get_logger

from ..clients import Clients
from ..utils.credentials import ensure_sync_credential

logger = get_logger(__name__)


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
    sync_cred = ensure_sync_credential(clients.cred)
    client = ApiManagementClient(sync_cred, clients.subscription_id)
    try:
        existing = await clients.run(client.api_management_service.get, resource_group, name)
        if existing and not force:
            return "exists", existing.as_dict()
    except HttpResponseError as exc:
        if exc.status_code != 404:
            logger.error("APIM retrieval failed: %s", exc.message)
            return "error", {"code": exc.status_code, "message": exc.message}
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
