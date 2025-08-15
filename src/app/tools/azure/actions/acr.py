from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..clients import Clients
from ..validators import validate_name


async def create_registry(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    name: str,
    sku: str = "Basic",
    admin_user_enabled: bool = True,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("acr", name):
        return "error", {"message": "invalid registry name"}
    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "location": location,
            "sku": sku,
            "admin_user_enabled": bool(admin_user_enabled),
            "tags": tags or {},
        }
    ok, existing = await _safe_get(
        clients.acr.registries.get, resource_group, name, clients=clients
    )
    if ok and existing and not force:
        return "exists", existing.as_dict()
    poller = await clients.run(
        clients.acr.registries.begin_create,
        resource_group,
        name,
        {
            "location": location,
            "sku": {"name": sku},
            "admin_user_enabled": bool(admin_user_enabled),
            "tags": tags or {},
        },
    )
    reg = await clients.run(poller.result)
    return "created", reg.as_dict()


async def _safe_get(
    pcall: Callable[..., Any],
    *args: Any,
    clients: Clients,
    **kwargs: Any,
) -> tuple[bool, Any]:
    try:
        res = await clients.run(pcall, *args, **kwargs)
        return True, res
    except Exception:
        return False, None
