from __future__ import annotations

import logging
from typing import Any

from azure.core.exceptions import HttpResponseError

from ..clients import Clients
from ..utils.credentials import ensure_sync_credential
from ..validators import validate_name

logger = logging.getLogger(__name__)


async def create_traffic_manager_profile(
    *,
    clients: Clients,
    resource_group: str,
    name: str,
    routing_method: str = "Performance",
    dns_ttl: int = 30,
    monitor_protocol: str = "HTTPS",
    monitor_port: int = 443,
    monitor_path: str = "/",
    endpoints: list[dict[str, Any]] | None = None,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid traffic manager profile name"}

    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "routing_method": routing_method,
            "endpoints": endpoints or [],
            "tags": tags or {},
        }

    from azure.mgmt.trafficmanager import TrafficManagerManagementClient
    from azure.mgmt.trafficmanager.models import (
        DnsConfig,
        Endpoint,
        MonitorConfig,
        Profile,
    )

    sync_cred = ensure_sync_credential(clients.cred)
    tm_client = TrafficManagerManagementClient(sync_cred, clients.subscription_id)

    try:
        try:
            existing = await clients.run(tm_client.profiles.get, resource_group, name)
            if existing and not force:
                return "exists", existing.as_dict()
        except HttpResponseError as exc:
            if exc.status_code != 404:
                logger.error("Traffic manager profile retrieval failed: %s", exc.message)
                return "error", {"code": exc.status_code, "message": exc.message}

        profile = Profile(
            location="global",
            profile_status="Enabled",
            traffic_routing_method=routing_method,
            dns_config=DnsConfig(
                relative_name=name,
                ttl=dns_ttl,
            ),
            monitor_config=MonitorConfig(
                profile_monitor_status="CheckingEndpoints",
                protocol=monitor_protocol,
                port=monitor_port,
                path=monitor_path,
                interval_in_seconds=30,
                timeout_in_seconds=10,
                tolerated_number_of_failures=3,
            ),
            endpoints=[],
            tags=tags or {},
        )

        result = await clients.run(
            tm_client.profiles.create_or_update,
            resource_group,
            name,
            profile,
        )

        if endpoints:
            for idx, endpoint_config in enumerate(endpoints):
                endpoint = Endpoint(
                    name=endpoint_config.get("name", f"{name}-endpoint-{idx}"),
                    type="Microsoft.Network/trafficManagerProfiles/azureEndpoints",
                    target_resource_id=endpoint_config.get("target_resource_id"),
                    target=endpoint_config.get("target"),
                    endpoint_status="Enabled",
                    weight=endpoint_config.get("weight", 100),
                    priority=endpoint_config.get("priority", idx + 1),
                    endpoint_location=endpoint_config.get("location"),
                )
                await clients.run(
                    tm_client.endpoints.create_or_update,
                    resource_group,
                    name,
                    "azureEndpoints",
                    endpoint.name,
                    endpoint,
                )

        return "created", result.as_dict()
    except HttpResponseError as exc:
        logger.error("Traffic manager profile create_or_update failed: %s", exc.message)
        return "error", {"code": exc.status_code, "message": exc.message}
    except Exception as exc:
        logger.exception("Unexpected error while creating traffic manager profile")
        return "error", {"message": str(exc)}
    finally:
        close = getattr(sync_cred, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                logger.debug("Credential close raised but was ignored")
