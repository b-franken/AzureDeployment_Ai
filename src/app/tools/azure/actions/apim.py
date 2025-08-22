from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from azure.core.credentials import AccessToken, TokenCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import HttpResponseError
from azure.mgmt.apimanagement import ApiManagementClient
from azure.mgmt.apimanagement.models import (
    ApiManagementServiceResource,
    ApiManagementServiceSkuProperties,
)

from ..clients import Clients

logger = logging.getLogger(__name__)


class _AsyncToSyncCredential(TokenCredential):
    def __init__(self, async_cred: AsyncTokenCredential) -> None:
        self._async_cred = async_cred

    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return cast(
                AccessToken, loop.run_until_complete(self._async_cred.get_token(*scopes, **kwargs))
            )
        finally:
            loop.close()

    def close(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            aclose = getattr(self._async_cred, "aclose", None)
            if callable(aclose):
                loop.run_until_complete(aclose())
        finally:
            loop.close()


def _ensure_sync_credential(cred: TokenCredential | AsyncTokenCredential) -> TokenCredential:
    if isinstance(cred, AsyncTokenCredential):
        return _AsyncToSyncCredential(cred)
    return cred


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
    sync_cred = _ensure_sync_credential(clients.cred)
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
