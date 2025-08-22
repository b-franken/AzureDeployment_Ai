from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, cast

from azure.core.credentials import AccessToken, TokenCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import HttpResponseError
from azure.keyvault.secrets import SecretClient
from azure.mgmt.keyvault.models import Sku as KvSku
from azure.mgmt.keyvault.models import VaultCreateOrUpdateParameters, VaultProperties

from ..clients import Clients

logger = logging.getLogger(__name__)


class _AsyncToSyncCredential(TokenCredential):
    def __init__(self, async_cred: AsyncTokenCredential) -> None:
        self._async_cred = async_cred

    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return cast(AccessToken, loop.run_until_complete(self._async_cred.get_token(*scopes, **kwargs)))
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
    params = VaultCreateOrUpdateParameters(
        location=location, properties=props, tags=tags or {})
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
    sync_cred = _ensure_sync_credential(clients.cred)
    sec = SecretClient(vault_url=url, credential=sync_cred)
    try:
        s = await clients.run(sec.set_secret, secret_name, secret_value)
        return "created", {"id": s.id}
    except HttpResponseError as exc:
        logger.error("Failed to set secret: %s", exc.message)
        return "error", {"code": exc.status_code, "message": exc.message}


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
