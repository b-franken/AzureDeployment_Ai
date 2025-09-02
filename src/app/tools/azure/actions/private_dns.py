from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from azure.core.exceptions import HttpResponseError

from app.common.async_pool import bounded_gather

from app.core.logging import get_logger
from ..clients import Clients
from ..validators import validate_name

logger = get_logger(__name__)
_PCall = Callable[..., Any]


async def _safe_get(pcall: _PCall, *args: Any, clients: Clients, **kwargs: Any) -> tuple[bool, Any]:
    try:
        res = await clients.run(pcall, *args, **kwargs)
        return True, res
    except HttpResponseError as exc:
        if exc.status_code == 404:
            return True, None
        logger.error("Azure request failed: %s", exc.message)
        return False, {"code": exc.status_code, "message": exc.message}


async def create_private_dns_zone(
    *,
    clients: Clients,
    resource_group: str,
    zone_name: str,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, Any]:
    if not validate_name("generic", zone_name):
        return "error", {"message": "invalid private dns zone name"}
    if dry_run:
        return "plan", {
            "zone": zone_name,
            "resource_group": resource_group,
            "tags": tags or {},
        }
    ok, existing = await _safe_get(
        clients.pdns.private_zones.get, resource_group, zone_name, clients=clients
    )
    if not ok:
        return "error", existing
    if existing and not force:
        return "exists", existing.as_dict()
    params = {"location": "global", "tags": tags or {}}
    poller = await clients.run(
        clients.pdns.private_zones.begin_create_or_update,
        resource_group,
        zone_name,
        params,
    )
    zone = await clients.run(poller.result)
    return "created", zone.as_dict()


async def link_private_dns_zone(
    *,
    clients: Clients,
    resource_group: str,
    zone_name: str,
    vnet_resource_group: str,
    vnet_name: str,
    link_name: str,
    registration_enabled: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, Any]:
    if not validate_name("generic", link_name):
        return "error", {"message": "invalid link name"}
    if dry_run:
        return "plan", {
            "zone": zone_name,
            "link_name": link_name,
            "vnet": f"{vnet_resource_group}/{vnet_name}",
            "registration_enabled": bool(registration_enabled),
        }
    vnet_coro = clients.run(clients.net.virtual_networks.get, vnet_resource_group, vnet_name)
    link_coro = _safe_get(
        clients.pdns.virtual_network_links.get,
        resource_group,
        zone_name,
        link_name,
        clients=clients,
    )
    vnet, link_tuple = await bounded_gather(vnet_coro, link_coro, limit=8)
    ok, existing = link_tuple
    if not ok:
        return "error", existing
    if existing and not force:
        return "exists", existing.as_dict()
    params = {
        "location": "global",
        "virtual_network": {"id": vnet.id},
        "registration_enabled": bool(registration_enabled),
    }
    poller = await clients.run(
        clients.pdns.virtual_network_links.begin_create_or_update,
        resource_group,
        zone_name,
        link_name,
        params,
    )
    link = await clients.run(poller.result)
    return "created", link.as_dict()
