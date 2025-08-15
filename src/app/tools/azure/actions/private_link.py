from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..clients import Clients
from ..validators import validate_name

_PCall = Callable[..., Any]


async def _safe_get(
    pcall: _PCall, *args: Any, clients: Clients, **kwargs: Any
) -> tuple[bool, Any]:
    try:
        res = await clients.run(pcall, *args, **kwargs)
        return True, res
    except Exception:
        return False, None


async def create_private_endpoint(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    name: str,
    vnet_name: str,
    subnet_name: str,
    target_resource_id: str,
    group_ids: list[str] | None = None,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, Any]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid private endpoint name"}
    gids = group_ids or []
    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "location": location,
            "vnet": vnet_name,
            "subnet": subnet_name,
            "target_resource_id": target_resource_id,
            "group_ids": gids,
            "tags": tags or {},
        }
    ok, existing = await _safe_get(
        clients.net.private_endpoints.get, resource_group, name, clients=clients
    )
    if ok and existing and not force:
        return "exists", existing.as_dict()
    subnet = await clients.run(
        clients.net.subnets.get, resource_group, vnet_name, subnet_name
    )
    conn = [
        {
            "name": "default",
            "private_link_service_id": target_resource_id,
            "group_ids": gids,
        }
    ]
    params = {
        "location": location,
        "subnet": {"id": subnet.id},
        "private_link_service_connections": conn,
        "tags": tags or {},
    }
    poller = await clients.run(
        clients.net.private_endpoints.begin_create_or_update,
        resource_group,
        name,
        params,
    )
    pe = await clients.run(poller.result)
    return "created", pe.as_dict()
