from __future__ import annotations

from collections.abc import Callable
from typing import Any

import logging
from azure.core.exceptions import HttpResponseError
from azure.keyvault.secrets import SecretClient
from azure.mgmt.keyvault.models import Sku as KvSku
from azure.mgmt.keyvault.models import VaultCreateOrUpdateParameters, VaultProperties

from ..clients import Clients

logger = logging.getLogger(__name__)


async def create_keyvault(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    vault_name: str,
    tenant_id: str,
    enable_rbac: bool = True,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if dry_run:
        return "plan", {
            "vault_name": vault_name,
            "resource_group": resource_group,
            "location": location,
            "enable_rbac": bool(enable_rbac),
            "tags": tags or {},
        }
    ok, existing = await _safe_get(
        clients.kv.vaults.get, resource_group, vault_name, clients=clients
    )
    if not ok:
        return "error", existing
    if existing and not force:
        summary = (
            "key vault exists with RBAC enabled"
            if existing.properties.enable_rbac_authorization
            else "key vault exists with access policies"
        )
        return "exists", {"summary": summary, **existing.as_dict()}
    props = VaultProperties(
        tenant_id=tenant_id,
        sku=KvSku(name="standard", family="A"),
        access_policies=[],
        enable_rbac_authorization=bool(enable_rbac),
        enable_purge_protection=True,
    )
    params = VaultCreateOrUpdateParameters(location=location, properties=props, tags=tags or {})
    poller = await clients.run(
        clients.kv.vaults.begin_create_or_update, resource_group, vault_name, params
    )
    vault = await clients.run(poller.result)
    note = "rbac mode enabled" if bool(enable_rbac) else "access policies mode"
    return "created", {"note": note, **vault.as_dict()}


async def set_keyvault_secret(
    *,
    clients: Clients,
    vault_name: str,
    secret_name: str,
    secret_value: str,
    dry_run: bool = False,
) -> tuple[str, object]:
    if dry_run:
        return "plan", {"vault": vault_name, "secret": secret_name}
    url = f"https://{vault_name}.vault.azure.net"
    sec = SecretClient(vault_url=url, credential=clients.cred)
    s = await clients.run(sec.set_secret, secret_name, secret_value)
    return "created", {"id": s.id}


async def _safe_get(
    pcall: Callable[..., Any],
    *args: Any,
    clients: Clients,
    **kwargs: Any,
) -> tuple[bool, Any]:
    try:
        res = await clients.run(pcall, *args, **kwargs)
        return True, res
    except HttpResponseError as exc:
        if exc.status_code == 404:
            return True, None
        logger.error("Azure request failed: %s", exc.message)
        return False, {"code": exc.status_code, "message": exc.message}
