from __future__ import annotations

import logging
from typing import Any

from ..clients import Clients
from ..idempotency import safe_get
from ..validators import validate_location

logger = logging.getLogger(__name__)


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
    logger.info(
        f"create_resource_group called: resource_group={resource_group}, location={location}, dry_run={dry_run}, force={force}"
    )

    if not validate_location(location):
        available = ["westeurope", "northeurope", "uksouth", "eastus"]
        logger.error(f"Invalid location provided: {location}")
        return "error", f"Invalid location. Use one of: {', '.join(available)}"

    if dry_run:
        logger.info("Returning plan only due to dry_run=True")
        return "plan", {
            "resource_group": resource_group,
            "location": location,
            "tags": tags,
        }

    logger.info(f"Checking if resource group {resource_group} already exists...")
    _, existing = await safe_get(clients.res.resource_groups.get, resource_group)
    if existing and not force:
        logger.info(f"Resource group {resource_group} already exists, returning existing data")
        return "exists", existing.as_dict()

    logger.info(f"Creating new resource group {resource_group} in {location} with tags: {tags}")
    try:
        result = await clients.run(
            clients.res.resource_groups.create_or_update,
            resource_group,
            {"location": location, "tags": tags},
        )
        logger.info(f"Resource group {resource_group} created successfully!")
        return "created", result.as_dict()
    except Exception as e:
        logger.error(f"Failed to create resource group {resource_group}: {e!s}")
        return "error", f"Failed to create resource group: {e!s}"
