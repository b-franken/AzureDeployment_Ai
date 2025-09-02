from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from azure.core.exceptions import HttpResponseError

from app.core.logging import get_logger
from ..clients import Clients
from ..validators import validate_name

logger = get_logger(__name__)


async def _safe_get(
    pcall: Callable[..., Awaitable[Any]], *args: Any, clients: Clients, **kwargs: Any
) -> tuple[bool, Any]:
    try:
        res = await clients.run(pcall, *args, **kwargs)
        return True, res
    except HttpResponseError as exc:
        if exc.status_code == 404:
            return True, None
        logger.error("Azure request failed: %s", exc.message)
        return False, {"code": exc.status_code, "message": exc.message}


async def create_user_assigned_identity(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    name: str,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid identity name"}
    if dry_run:
        return "plan", {
            "identity": name,
            "resource_group": resource_group,
            "location": location,
            "tags": tags or {},
        }
    ok, existing = await _safe_get(
        clients.msi.user_assigned_identities.get, resource_group, name, clients=clients
    )
    if not ok:
        return "error", existing
    if existing and not force:
        return "exists", existing.as_dict()
    params: dict[str, Any] = {"location": location, "tags": tags or {}}
    poller = await clients.run(
        clients.msi.user_assigned_identities.begin_create_or_update,
        resource_group,
        name,
        params,
    )
    ident = await clients.run(poller.result)
    return "created", ident.as_dict()
