from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from azure.core.exceptions import HttpResponseError
from azure.keyvault.secrets import SecretClient
from azure.mgmt.keyvault.models import Sku as KvSku
from azure.mgmt.keyvault.models import VaultCreateOrUpdateParameters, VaultProperties

from app.core.logging import get_logger
from ..clients import Clients
from ..utils.credentials import ensure_sync_credential

logger = get_logger(__name__)


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

    try:
        poller = await clients.run(
            clients.kv.vaults.begin_create_or_update, resource_group, vault_name, params
        )
        vault = await clients.run(poller.result)
        note = "rbac mode enabled" if bool(enable_rbac) else "access policies mode"
        return "created", {"note": note, **vault.as_dict()}
    except HttpResponseError as exc:
        logger.error("Key vault creation failed: %s", exc.message)
        return "error", {"code": exc.status_code, "message": exc.message}


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
    sync_cred = ensure_sync_credential(clients.cred)
    try:
        sec = SecretClient(vault_url=url, credential=sync_cred)
        s = await clients.run(sec.set_secret, secret_name, secret_value)
        return "created", {"id": s.id}
    except HttpResponseError as exc:
        logger.error("Failed to set secret: %s", exc.message)
        return "error", {"code": exc.status_code, "message": exc.message}
    except Exception as exc:
        logger.exception("Unexpected error while setting secret")
        return "error", {"message": str(exc)}
    finally:
        close = getattr(sync_cred, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                logger.debug("Credential close raised but was ignored")


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
