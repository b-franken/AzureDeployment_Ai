from __future__ import annotations

from collections.abc import Callable
from typing import Any

from azure.mgmt.web.models import (
    AppServicePlan,
    Site,
    SiteConfig,
    SkuDescription,
    StringDictionary,
    SwiftVirtualNetwork,
)

from ..clients import Clients
from ..validators import validate_name

_PCall = Callable[..., Any]


async def create_plan(
    *,
    clients: Clients,
    resource_group: str,
    name: str,
    location: str,
    sku: str,
    linux: bool = False,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, Any]:
    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "location": location,
            "sku": sku,
            "linux": bool(linux),
            "tags": tags or {},
        }
    ok, existing = await _safe_get(
        clients.web.app_service_plans.get, resource_group, name, clients=clients
    )
    if ok and existing and not force:
        return "exists", existing.as_dict()
    plan_obj = AppServicePlan(
        location=location, reserved=bool(linux), sku=SkuDescription(name=sku), tags=tags
    )
    poller = await clients.run(
        clients.web.app_service_plans.begin_create_or_update, resource_group, name, plan_obj
    )
    created = await clients.run(poller.result)
    return "created", created.as_dict()


async def create_webapp(
    *,
    clients: Clients,
    resource_group: str,
    name: str,
    plan: str,
    runtime: str | None = None,
    https_only: bool | None = None,
    always_on: bool | None = None,
    ftps_state: str | None = None,
    min_tls_version: str | None = None,
    health_check_path: str | None = None,
    client_affinity_enabled: bool | None = None,
    vnet_subnet_id: str | None = None,
    vnet_route_all_enabled: bool | None = None,
    app_settings: dict[str, str] | None = None,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, Any]:
    if not validate_name("webapp", name):
        return "error", {"message": "invalid webapp name"}
    p = await clients.run(clients.web.app_service_plans.get, resource_group, plan)
    if runtime and not getattr(p, "reserved", False):
        return "error", {"message": "runtime requires linux plan"}

    cfg_fields: dict[str, Any] = {}
    if runtime:
        cfg_fields["linux_fx_version"] = runtime
    if always_on is not None:
        cfg_fields["always_on"] = bool(always_on)
    if ftps_state is not None:
        cfg_fields["ftps_state"] = ftps_state
    if min_tls_version is not None:
        cfg_fields["min_tls_version"] = min_tls_version
    if health_check_path is not None:
        cfg_fields["health_check_path"] = health_check_path
    if vnet_route_all_enabled is not None:
        cfg_fields["vnet_route_all_enabled"] = bool(vnet_route_all_enabled)

    site_cfg = SiteConfig(**cfg_fields) if cfg_fields else None

    site_kwargs: dict[str, Any] = {
        "location": p.location,
        "server_farm_id": p.id,
        "site_config": site_cfg,
        "tags": tags,
    }
    if https_only is not None:
        site_kwargs["https_only"] = bool(https_only)
    if client_affinity_enabled is not None:
        site_kwargs["client_affinity_enabled"] = bool(client_affinity_enabled)

    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "plan": plan,
            "location": p.location,
            "runtime": runtime,
            "https_only": https_only,
            "always_on": always_on,
            "ftps_state": ftps_state,
            "min_tls_version": min_tls_version,
            "health_check_path": health_check_path,
            "client_affinity_enabled": client_affinity_enabled,
            "vnet_subnet_id": vnet_subnet_id,
            "vnet_route_all_enabled": vnet_route_all_enabled,
            "app_settings_keys": sorted(list((app_settings or {}).keys())),
            "tags": tags or {},
        }

    ok, existing = await _safe_get(clients.web.web_apps.get, resource_group, name, clients=clients)
    if ok and existing and not force:
        return "exists", existing.as_dict()

    site = Site(**site_kwargs)
    poller = await clients.run(
        clients.web.web_apps.begin_create_or_update, resource_group, name, site
    )
    await clients.run(poller.result)

    if app_settings:
        await clients.run(
            clients.web.web_apps.update_application_settings,
            resource_group,
            name,
            StringDictionary(properties=app_settings),
        )

    if vnet_subnet_id:
        swift = SwiftVirtualNetwork(subnet_resource_id=vnet_subnet_id)
        await clients.run(
            clients.web.web_apps.create_or_update_swift_virtual_network_connection,
            resource_group,
            name,
            swift,
        )

    final = await clients.run(clients.web.web_apps.get, resource_group, name)
    return "created", final.as_dict()


async def _safe_get(pcall: _PCall, *args: Any, clients: Clients, **kwargs: Any) -> tuple[bool, Any]:
    try:
        res = await clients.run(pcall, *args, **kwargs)
        return True, res
    except Exception:
        return False, None
