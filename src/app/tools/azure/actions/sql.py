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


async def create_sql(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    server_name: str,
    sql_admin_user: str,
    sql_admin_password: str,
    db_name: str | None = None,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, Any]:
    if not validate_name("sql_server", server_name):
        return "error", {"message": "invalid sql server name"}
    if dry_run:
        return "plan", {
            "server": server_name,
            "resource_group": resource_group,
            "location": location,
            "db": db_name or "",
            "tags": tags or {},
        }
    ok, existing = await _safe_get(
        clients.sql.servers.get, resource_group, server_name, clients=clients
    )
    if ok and existing and not force:
        server = existing
    else:
        poller = await clients.run(
            clients.sql.servers.begin_create_or_update,
            resource_group,
            server_name,
            {
                "location": location,
                "administrator_login": sql_admin_user,
                "administrator_login_password": sql_admin_password,
                "version": "12.0",
                "tags": tags or {},
            },
        )
        server = await clients.run(poller.result)
    db_out = None
    if db_name:
        okd, existing_db = await _safe_get(
            clients.sql.databases.get,
            resource_group,
            server_name,
            db_name,
            clients=clients,
        )
        if okd and existing_db and not force:
            db_out = existing_db.as_dict()
        else:
            dpoller = await clients.run(
                clients.sql.databases.begin_create_or_update,
                resource_group,
                server_name,
                db_name,
                {"location": location, "sku": {"name": "Basic"}, "tags": tags or {}},
            )
            db = await clients.run(dpoller.result)
            db_out = db.as_dict()
    return "created", {"server": server.as_dict(), "database": db_out}
