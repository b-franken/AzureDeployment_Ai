from __future__ import annotations

import uuid

import logging
from azure.core.exceptions import HttpResponseError

from ..clients import Clients
from ..idempotency import safe_get

logger = logging.getLogger(__name__)

ACR_PULL_ROLE_ID = "7f951dda-4ed3-4680-a7ca-43fe172d538d"


async def _assign_acr_pull(
    *,
    clients: Clients,
    subscription_id: str,
    resource_group: str,
    acr_name: str,
    principal_id: str,
) -> None:
    scope = (
        f"/subscriptions/{clients.subscription_id}"
        f"/resourceGroups/{resource_group}"
        "/providers/Microsoft.ContainerRegistry"
        f"/registries/{acr_name}"
    )
    existing = list(
        await clients.run(
            clients.auth.role_assignments.list_for_scope,
            scope,
            filter=f"assignedTo('{principal_id}')",
        )
    )
    for ra in existing:
        rid = getattr(getattr(ra, "properties", None), "role_definition_id", "") or ""
        if rid.endswith(ACR_PULL_ROLE_ID):
            return
    role_def_id = (
        f"/subscriptions/{clients.subscription_id}"
        "/providers/Microsoft.Authorization/roleDefinitions/"
        f"{ACR_PULL_ROLE_ID}"
    )
    await clients.run(
        clients.auth.role_assignments.create,
        scope,
        str(uuid.uuid4()),
        {
            "properties": {
                "role_definition_id": role_def_id,
                "principal_id": principal_id,
            }
        },
    )


async def create_aks(
    *,
    clients: Clients,
    tags: dict[str, str],
    dry_run: bool = False,
    resource_group: str,
    location: str,
    name: str,
    dns_prefix: str,
    node_count: int | None = None,
    network_plugin: str | None = None,
    pod_cidr: str | None = None,
    service_cidr: str | None = None,
    dns_service_ip: str | None = None,
    workload_identity_enabled: bool | None = None,
    azure_policy_enabled: bool | None = None,
    attach_acr: bool | None = None,
    acr_name: str | None = None,
    force: bool = False,
    **_: object,
) -> tuple[str, object]:
    count = node_count or 1
    nprofile: dict[str, object] = {}
    if network_plugin:
        nprofile["network_plugin"] = network_plugin
    if pod_cidr:
        nprofile["pod_cidr"] = pod_cidr
    if service_cidr:
        nprofile["service_cidr"] = service_cidr
    if dns_service_ip:
        nprofile["dns_service_ip"] = dns_service_ip
    wi = True if workload_identity_enabled is None else bool(workload_identity_enabled)
    apol = True if azure_policy_enabled is None else bool(azure_policy_enabled)
    if dry_run:
        return "plan", {
            "name": name,
            "rg": resource_group,
            "location": location,
            "dns_prefix": dns_prefix,
            "node_count": count,
            "network_profile": nprofile or None,
            "workload_identity": wi,
            "azure_policy_enabled": apol,
            "tags": tags,
        }
    ok, existing = await safe_get(clients.aks.managed_clusters.get, resource_group, name)
    if ok and existing and not force:
        return "exists", existing.as_dict()
    mc = {
        "location": location,
        "dns_prefix": dns_prefix,
        "agent_pool_profiles": [
            {
                "name": "nodepool1",
                "count": count,
                "vm_size": "Standard_DS2_v2",
                "os_type": "Linux",
                "type": "VirtualMachineScaleSets",
                "mode": "System",
            }
        ],
        "identity": {"type": "SystemAssigned"},
        "enable_rbac": True,
        "oidc_issuer_profile": {"enabled": wi},
        "network_profile": nprofile or None,
        "azure_policy_enabled": apol,
        "tags": tags,
    }
    poller = await clients.run(
        clients.aks.managed_clusters.begin_create_or_update, resource_group, name, mc
    )
    cluster = await clients.run(poller.result)
    principal = getattr(getattr(cluster, "identity", None), "principal_id", None)
    if attach_acr and acr_name and principal:
        try:
            await clients.run(clients.acr.registries.get, resource_group, acr_name)
            await _assign_acr_pull(
                clients=clients,
                subscription_id=clients.subscription_id,
                resource_group=resource_group,
                acr_name=acr_name,
                principal_id=principal,
            )
        except HttpResponseError as exc:
            logger.error("Failed to assign ACR pull role: %s", exc.message)
    return "created", cluster.as_dict()
