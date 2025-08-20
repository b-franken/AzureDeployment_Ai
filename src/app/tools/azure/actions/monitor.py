from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from azure.core.exceptions import HttpResponseError

from ..clients import Clients
from ..validators import validate_name

logger = logging.getLogger(__name__)


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


async def create_log_analytics_workspace(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    name: str,
    retention_in_days: int | None = None,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid workspace name"}
    if dry_run:
        return "plan", {
            "workspace": name,
            "resource_group": resource_group,
            "location": location,
            "retention_in_days": retention_in_days,
            "tags": tags or {},
        }
    ok, existing = await _safe_get(
        clients.law.workspaces.get, resource_group, name, clients=clients
    )
    if not ok:
        return "error", existing
    if existing and not force:
        return "exists", existing.as_dict()
    params: dict[str, Any] = {
        "location": location,
        "sku": {"name": "PerGB2018"},
        "retention_in_days": retention_in_days or 30,
        "tags": tags or {},
    }
    poller = await clients.run(
        clients.law.workspaces.begin_create_or_update, resource_group, name, params
    )
    ws = await clients.run(poller.result)
    return "created", ws.as_dict()


async def create_app_insights(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    name: str,
    application_type: str | None = None,
    workspace_resource_id: str | None = None,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid application insights name"}
    app_type = application_type or "web"
    if dry_run:
        return "plan", {
            "component": name,
            "resource_group": resource_group,
            "location": location,
            "application_type": app_type,
            "workspace_resource_id": workspace_resource_id or "",
            "tags": tags or {},
        }
    ok, existing = await _safe_get(
        clients.appi.components.get, resource_group, name, clients=clients
    )
    if not ok:
        return "error", existing
    if existing and not force:
        return "exists", existing.as_dict()
    params: dict[str, Any] = {
        "location": location,
        "kind": "web",
        "application_type": app_type,
        "workspace_resource_id": workspace_resource_id,
        "tags": tags or {},
    }
    poller = await clients.run(
        clients.appi.components.begin_create_or_update,
        resource_group,
        name,
        params,
    )
    comp = await clients.run(poller.result)
    return "created", comp.as_dict()
