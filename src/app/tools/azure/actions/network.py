from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..clients import Clients
from ..validators import validate_name


async def create_vnet(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    name: str,
    address_prefix: str,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("vnet", name):
        return "error", {"message": "invalid vnet name"}
    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "location": location,
            "address_prefix": address_prefix,
            "tags": tags or {},
        }
    ok, existing = await _safe_get(
        clients.net.virtual_networks.get, resource_group, name, clients=clients
    )
    if ok and existing and not force:
        return "exists", existing.as_dict()
    poller = await clients.run(
        clients.net.virtual_networks.begin_create_or_update,
        resource_group,
        name,
        {
            "location": location,
            "tags": tags or {},
            "address_space": {"address_prefixes": [address_prefix]},
        },
    )
    vnet = await clients.run(poller.result)
    return "created", vnet.as_dict()


async def create_subnet(
    *,
    clients: Clients,
    resource_group: str,
    vnet_name: str,
    subnet_name: str,
    address_prefix: str,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", subnet_name):
        return "error", {"message": "invalid subnet name"}
    if dry_run:
        return "plan", {
            "vnet": vnet_name,
            "subnet": subnet_name,
            "resource_group": resource_group,
            "prefix": address_prefix,
        }
    ok, existing = await _safe_get(
        clients.net.subnets.get, resource_group, vnet_name, subnet_name, clients=clients
    )
    if ok and existing and not force:
        return "exists", existing.as_dict()
    poller = await clients.run(
        clients.net.subnets.begin_create_or_update,
        resource_group,
        vnet_name,
        subnet_name,
        {"address_prefix": address_prefix},
    )
    subnet = await clients.run(poller.result)
    return "created", subnet.as_dict()


async def create_public_ip(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    public_ip_name: str,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", public_ip_name):
        return "error", {"message": "invalid public ip name"}
    if dry_run:
        return "plan", {
            "name": public_ip_name,
            "resource_group": resource_group,
            "location": location,
        }
    ok, existing = await _safe_get(
        clients.net.public_ip_addresses.get,
        resource_group,
        public_ip_name,
        clients=clients,
    )
    if ok and existing and not force:
        return "exists", existing.as_dict()
    poller = await clients.run(
        clients.net.public_ip_addresses.begin_create_or_update,
        resource_group,
        public_ip_name,
        {
            "location": location,
            "public_ip_allocation_method": "Static",
            "sku": {"name": "Standard"},
            "tags": tags or {},
        },
    )
    pip = await clients.run(poller.result)
    return "created", pip.as_dict()


async def create_nsg(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    nsg_name: str,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", nsg_name):
        return "error", {"message": "invalid nsg name"}
    if dry_run:
        return "plan", {
            "name": nsg_name,
            "resource_group": resource_group,
            "location": location,
        }
    ok, existing = await _safe_get(
        clients.net.network_security_groups.get,
        resource_group,
        nsg_name,
        clients=clients,
    )
    if ok and existing and not force:
        return "exists", existing.as_dict()
    poller = await clients.run(
        clients.net.network_security_groups.begin_create_or_update,
        resource_group,
        nsg_name,
        {"location": location, "security_rules": [], "tags": tags or {}},
    )
    nsg = await clients.run(poller.result)
    return "created", nsg.as_dict()


async def create_lb(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    lb_name: str,
    public_ip_name: str,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", lb_name):
        return "error", {"message": "invalid load balancer name"}
    if dry_run:
        return "plan", {
            "name": lb_name,
            "resource_group": resource_group,
            "location": location,
            "pip": public_ip_name,
        }
    ok, existing = await _safe_get(
        clients.net.load_balancers.get, resource_group, lb_name, clients=clients
    )
    if ok and existing and not force:
        return "exists", existing.as_dict()
    pip = await clients.run(clients.net.public_ip_addresses.get, resource_group, public_ip_name)
    feip_cfg: list[dict[str, object]] = [
        {"name": "LoadBalancerFrontEnd", "public_ip_address": {"id": pip.id}}
    ]
    params: dict[str, object] = {
        "location": location,
        "sku": {"name": "Standard"},
        "frontend_ip_configurations": feip_cfg,
        "backend_address_pools": [{"name": "lb-backend"}],
        "load_balancing_rules": [],
        "probes": [],
        "tags": tags or {},
    }
    poller = await clients.run(
        clients.net.load_balancers.begin_create_or_update,
        resource_group,
        lb_name,
        params,
    )
    lb = await clients.run(poller.result)
    return "created", lb.as_dict()


async def create_app_gateway(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    name: str,
    vnet_name: str,
    subnet_name: str,
    public_ip_name: str,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid application gateway name"}
    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "location": location,
        }
    ok, existing = await _safe_get(
        clients.net.application_gateways.get, resource_group, name, clients=clients
    )
    if ok and existing and not force:
        return "exists", existing.as_dict()
    subnet = await clients.run(clients.net.subnets.get, resource_group, vnet_name, subnet_name)
    pip = await clients.run(clients.net.public_ip_addresses.get, resource_group, public_ip_name)
    params: dict[str, object] = {
        "location": location,
        "sku": {"name": "WAF_v2", "tier": "WAF_v2", "capacity": 1},
        "gateway_ip_configurations": [{"name": "appGwIpConfig", "subnet": {"id": subnet.id}}],
        "frontend_ip_configurations": [
            {"name": "appGwFrontendIP", "public_ip_address": {"id": pip.id}}
        ],
        "frontend_ports": [{"name": "appGwFrontendPort", "port": 80}],
        "backend_address_pools": [{"name": "appGwBackendPool"}],
        "backend_http_settings_collection": [
            {
                "name": "appGwBackendHttpSettings",
                "port": 80,
                "protocol": "Http",
                "cookie_based_affinity": "Disabled",
            }
        ],
        "http_listeners": [
            {
                "name": "appGwHttpListener",
                "frontend_ip_configuration": {"name": "appGwFrontendIP"},
                "frontend_port": {"name": "appGwFrontendPort"},
                "protocol": "Http",
            }
        ],
        "request_routing_rules": [
            {
                "name": "rule1",
                "rule_type": "Basic",
                "http_listener": {"name": "appGwHttpListener"},
                "backend_address_pool": {"name": "appGwBackendPool"},
                "backend_http_settings": {"name": "appGwBackendHttpSettings"},
            }
        ],
        "tags": tags or {},
    }
    poller = await clients.run(
        clients.net.application_gateways.begin_create_or_update,
        resource_group,
        name,
        params,
    )
    ag = await clients.run(poller.result)
    return "created", ag.as_dict()


async def _safe_get(
    pcall: Callable[..., Any], *args: Any, clients: Clients, **kwargs: Any
) -> tuple[bool, Any]:
    try:
        res = await clients.run(pcall, *args, **kwargs)
        return True, res
    except Exception:
        return False, None
