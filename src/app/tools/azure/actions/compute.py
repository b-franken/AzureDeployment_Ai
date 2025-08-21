from __future__ import annotations
import logging
from collections.abc import Callable
from typing import Any
from app.common.async_pool import bounded_gather
from azure.core.exceptions import HttpResponseError
from ..clients import Clients
from ..validators import validate_name

logger = logging.getLogger(__name__)


async def create_vm(
    *,
    clients: Clients,
    resource_group: str,
    location: str,
    name: str,
    vm_size: str,
    admin_username: str,
    ssh_public_key: str,
    vnet_name: str,
    subnet_name: str,
    image_id: str | None = None,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid vm name"}
    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "location": location,
            "size": vm_size,
            "vnet": vnet_name,
            "subnet": subnet_name,
            "tags": tags or {},
        }
    ok, existing = await _safe_get(
        clients.cmp.virtual_machines.get, resource_group, name, clients=clients
    )
    if not ok:
        return "error", existing
    if existing and not force:
        return "exists", {"vmId": existing.vm_id, "id": existing.id}
    nic_name = f"{name}-nic"
    subnet_coro = clients.run(clients.net.subnets.get,
                              resource_group, vnet_name, subnet_name)
    nic_coro = _safe_get(clients.net.network_interfaces.get,
                         resource_group, nic_name, clients=clients)
    subnet, nic_tuple = await bounded_gather(subnet_coro, nic_coro, limit=8)
    nic_ok, nic_existing = nic_tuple
    if not nic_ok:
        return "error", nic_existing
    if not nic_existing:
        npoller = await clients.run(
            clients.net.network_interfaces.begin_create_or_update,
            resource_group,
            nic_name,
            {
                "location": location,
                "ip_configurations": [{"name": "ipconfig1", "subnet": {"id": subnet.id}}],
                "tags": tags or {},
            },
        )
        nic_existing = await clients.run(npoller.result)
    publisher, offer, sku_img, version = (
        ("Canonical", "UbuntuServer", "18.04-LTS", "latest")
        if not image_id
        else (None, None, None, None)
    )
    vm_params = {
        "location": location,
        "hardware_profile": {"vm_size": vm_size},
        "os_profile": {
            "computer_name": name,
            "admin_username": admin_username,
            "linux_configuration": {
                "disable_password_authentication": True,
                "ssh": {
                    "public_keys": [
                        {
                            "path": f"/home/{admin_username}/.ssh/authorized_keys",
                            "key_data": ssh_public_key,
                        }
                    ]
                },
            },
        },
        "storage_profile": (
            {
                "image_reference": {
                    "publisher": publisher,
                    "offer": offer,
                    "sku": sku_img,
                    "version": version,
                }
            }
            if not image_id
            else {"image_reference": {"id": image_id}}
        ),
        "network_profile": {"network_interfaces": [{"id": nic_existing.id, "primary": True}]},
        "tags": tags or {},
    }
    poller = await clients.run(
        clients.cmp.virtual_machines.begin_create_or_update,
        resource_group,
        name,
        vm_params,
    )
    vm = await clients.run(poller.result)
    return "created", {"vmId": vm.vm_id, "id": vm.id}


async def _safe_get(
    pcall: Callable[..., Any],
    *args: Any,
    clients: Clients,
    **kwargs: Any,
) -> tuple[bool, Any]:
    try:
        res = await clients.run(pcall, *args, **kwargs)
        return True, res
    except HttpResponseError as exc:
        if exc.status_code == 404:
            return True, None
        logger.error("Azure request failed: %s", exc.message)
        return False, {"code": exc.status_code, "message": exc.message}
