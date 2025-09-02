from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from azure.core.exceptions import HttpResponseError

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


async def create_redis(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    name: str,
    sku: str = "Standard",
    family: str = "C",
    capacity: int = 1,
    enable_non_ssl_port: bool = False,
    minimum_tls_version: str = "1.2",
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, Any]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid redis name"}
    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "location": location,
            "sku": sku,
            "family": family,
            "capacity": capacity,
            "enable_non_ssl_port": bool(enable_non_ssl_port),
            "minimum_tls_version": minimum_tls_version,
            "tags": tags or {},
        }
    ok, existing = await _safe_get(clients.redis.redis.get, resource_group, name, clients=clients)
    if not ok:
        return "error", existing
    if existing and not force:
        return "exists", existing.as_dict()
    params = {
        "location": location,
        "sku": {"name": sku, "family": family, "capacity": int(capacity)},
        "enable_non_ssl_port": bool(enable_non_ssl_port),
        "minimum_tls_version": minimum_tls_version,
        "tags": tags or {},
    }
    poller = await clients.run(clients.redis.redis.begin_create, resource_group, name, params)
    cache = await clients.run(poller.result)
    return "created", cache.as_dict()
