from __future__ import annotations

from typing import Any

from ..clients import Clients
from ..idempotency import safe_get
from ..validators import validate_location


async def create_resource_group(
    *,
    clients: Clients,
    tags: dict[str, str],
    dry_run: bool = False,
    resource_group: str,
    location: str,
    force: bool = False,
    **kwargs: Any,
) -> tuple[str, Any]:
    if not validate_location(location):
        available = ["westeurope", "northeurope", "uksouth", "eastus"]
        return "error", f"Invalid location. Use one of: {', '.join(available)}"

    if dry_run:
        return "plan", {"resource_group": resource_group, "location": location, "tags": tags}

    _, existing = await safe_get(clients.res.resource_groups.get, resource_group)
    if existing and not force:
        return "exists", existing.as_dict()

    result = await clients.run(
        clients.res.resource_groups.create_or_update,
        resource_group,
        {"location": location, "tags": tags},
    )
    return "created", result.as_dict()
