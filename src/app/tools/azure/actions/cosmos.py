from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..clients import Clients
from ..validators import validate_name


async def create_cosmos_account(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    account_name: str,
    kind: str | None = None,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", account_name):
        return "error", {"message": "invalid cosmos account name"}
    acct_kind = kind or "GlobalDocumentDB"
    if dry_run:
        return "plan", {
            "account": account_name,
            "resource_group": resource_group,
            "location": location,
            "kind": acct_kind,
            "tags": tags or {},
        }
    ok, existing = await _safe_get(
        clients.cosmos.database_accounts.get, resource_group, account_name, clients=clients
    )
    if ok and existing and not force:
        return "exists", existing.as_dict()
    poller = await clients.run(
        clients.cosmos.database_accounts.begin_create_or_update,
        resource_group,
        account_name,
        {
            "location": location,
            "locations": [{"location_name": location, "failover_priority": 0}],
            "kind": acct_kind,
            "database_account_offer_type": "Standard",
            "consistency_policy": {"default_consistency_level": "Session"},
            "tags": tags or {},
        },
    )
    acc = await clients.run(poller.result)
    return "created", acc.as_dict()


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
