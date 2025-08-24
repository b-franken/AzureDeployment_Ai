from __future__ import annotations

import logging
from typing import Any

from azure.core.exceptions import HttpResponseError, ResourceExistsError
from azure.storage.blob import BlobServiceClient
from azure.storage.fileshare import ShareServiceClient

from ..clients import Clients
from ..idempotency import safe_get
from ..utils.credentials import ensure_sync_credential
from ..validators import validate_name

logger = logging.getLogger(__name__)


async def create_storage_account(
    *,
    clients: Clients,
    tags: dict[str, str],
    dry_run: bool = False,
    resource_group: str,
    location: str,
    name: str,
    sku: str | None = None,
    access_tier: str | None = None,
    force: bool = False,
    **_: Any,
) -> tuple[str, Any]:
    if not validate_name("storage", name):
        return "error", "Invalid storage account name (3-24 lowercase letters/numbers)"

    storage_sku = sku or "Standard_LRS"
    valid_skus = [
        "Standard_LRS",
        "Standard_GRS",
        "Standard_RAGRS",
        "Standard_ZRS",
        "Premium_LRS",
        "Premium_ZRS",
    ]
    if storage_sku not in valid_skus:
        storage_sku = "Standard_LRS"

    storage_tier = access_tier or "Hot"
    if storage_tier not in ["Hot", "Cool"]:
        storage_tier = "Hot"

    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "location": location,
            "sku": storage_sku,
            "access_tier": storage_tier,
            "tags": tags,
        }

    ok, existing = await safe_get(
        clients.stor.storage_accounts.get_properties, resource_group, name
    )
    if ok and existing and not force:
        return "exists", existing.as_dict()

    params = {
        "location": location,
        "sku": {"name": storage_sku},
        "kind": "StorageV2",
        "access_tier": storage_tier,
        "tags": tags,
        "enable_https_traffic_only": True,
        "minimum_tls_version": "TLS1_2",
        "allow_blob_public_access": False,
        "network_rule_set": {"default_action": "Allow", "bypass": "AzureServices"},
    }

    poller = await clients.run(
        clients.stor.storage_accounts.begin_create, resource_group, name, params
    )
    acct = await clients.run(poller.result)
    return "created", acct.as_dict()


async def create_blob_container(
    *,
    clients: Clients,
    tags: dict[str, str],
    dry_run: bool = False,
    resource_group: str,
    name: str,
    container_name: str,
    **_: Any,
) -> tuple[str, Any]:
    if not validate_name("generic", container_name):
        return "error", "Invalid container name"

    if dry_run:
        return "plan", {"account": name, "container": container_name}

    account_url = f"https://{name}.blob.core.windows.net"
    sync_cred = ensure_sync_credential(clients.cred)
    svc = BlobServiceClient(account_url=account_url, credential=sync_cred)

    try:
        await clients.run(svc.create_container, container_name, metadata=tags)
        return "created", {"account": name, "container": container_name}
    except ResourceExistsError:
        return "exists", {"account": name, "container": container_name}
    except HttpResponseError as exc:
        logger.error("Failed to create container: %s", exc.message)
        return "error", {"code": exc.status_code, "message": exc.message}


async def create_file_share(
    *,
    clients: Clients,
    tags: dict[str, str],
    dry_run: bool = False,
    resource_group: str,
    name: str,
    share_name: str,
    **_: Any,
) -> tuple[str, Any]:
    if not validate_name("generic", share_name):
        return "error", "Invalid share name"

    if dry_run:
        return "plan", {"account": name, "share": share_name}

    account_url = f"https://{name}.file.core.windows.net"
    sync_cred = ensure_sync_credential(clients.cred)
    svc = ShareServiceClient(account_url=account_url, credential=sync_cred)

    try:
        await clients.run(svc.create_share, share_name, metadata=tags)
        return "created", {"account": name, "share": share_name}
    except ResourceExistsError:
        return "exists", {"account": name, "share": share_name}
    except HttpResponseError as exc:
        logger.error("Failed to create file share: %s", exc.message)
        return "error", {"code": exc.status_code, "message": exc.message}
