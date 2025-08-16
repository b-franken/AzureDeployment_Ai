from __future__ import annotations

from typing import Any

from ..clients import Clients
from ..validators import validate_name


async def create_front_door(
    *,
    clients: Clients,
    resource_group: str,
    name: str,
    backend_address: str,
    backend_host_header: str | None = None,
    routing_rules: list[dict[str, Any]] | None = None,
    health_probe_settings: dict[str, Any] | None = None,
    load_balancing_settings: dict[str, Any] | None = None,
    waf_policy_id: str | None = None,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid front door name"}

    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "backend_address": backend_address,
            "routing_rules": routing_rules or [],
            "tags": tags or {},
        }

    from azure.mgmt.frontdoor import FrontDoorManagementClient
    from azure.mgmt.frontdoor.models import (
        Backend,
        BackendPool,
        ForwardingConfiguration,
        FrontDoor,
        FrontendEndpoint,
        FrontendEndpointUpdateParametersWebApplicationFirewallPolicyLink,
        HealthProbeSettingsModel,
        LoadBalancingSettingsModel,
        RoutingRule,
        SubResource,
    )

    fd_client = FrontDoorManagementClient(clients.cred, clients.subscription_id)

    try:
        existing = await clients.run(fd_client.front_doors.get, resource_group, name)
        if existing and not force:
            return "exists", existing.as_dict()
    except Exception:
        pass

    frontend_endpoint_name = f"{name}-frontend"
    backend_pool_name = f"{name}-backend-pool"
    routing_rule_name = f"{name}-routing-rule"
    health_probe_name = f"{name}-health-probe"
    load_balancing_name = f"{name}-load-balancing"

    health_probe = HealthProbeSettingsModel(
        name=health_probe_name,
        path=health_probe_settings.get("path", "/") if health_probe_settings else "/",
        protocol=(
            health_probe_settings.get("protocol", "Https") if health_probe_settings else "Https"
        ),
        interval_in_seconds=(
            health_probe_settings.get("interval", 30) if health_probe_settings else 30
        ),
    )

    load_balancing = LoadBalancingSettingsModel(
        name=load_balancing_name,
        sample_size=load_balancing_settings.get("sample_size", 4) if load_balancing_settings else 4,
        successful_samples_required=(
            load_balancing_settings.get("successful_samples_required", 2)
            if load_balancing_settings
            else 2
        ),
        additional_latency_milliseconds=(
            load_balancing_settings.get("additional_latency", 0) if load_balancing_settings else 0
        ),
    )

    backend = Backend(
        address=backend_address,
        backend_host_header=backend_host_header or backend_address,
        http_port=80,
        https_port=443,
        priority=1,
        weight=50,
        enabled_state="Enabled",
    )

    backend_pool = BackendPool(
        name=backend_pool_name,
        backends=[backend],
        health_probe_settings=SubResource(
            id=f"/subscriptions/{clients.subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/frontDoors/{name}/healthProbeSettings/{health_probe_name}"
        ),
        load_balancing_settings=SubResource(
            id=f"/subscriptions/{clients.subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/frontDoors/{name}/loadBalancingSettings/{load_balancing_name}"
        ),
    )

    frontend_endpoint = FrontendEndpoint(
        name=frontend_endpoint_name,
        host_name=f"{name}.azurefd.net",
        session_affinity_enabled_state="Disabled",
        web_application_firewall_policy_link=(
            FrontendEndpointUpdateParametersWebApplicationFirewallPolicyLink(id=waf_policy_id)
            if waf_policy_id
            else None
        ),
    )

    routing_rule = RoutingRule(
        name=routing_rule_name,
        frontend_endpoints=[
            SubResource(
                id=f"/subscriptions/{clients.subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/frontDoors/{name}/frontendEndpoints/{frontend_endpoint_name}"
            )
        ],
        accepted_protocols=["Http", "Https"],
        patterns_to_match=["/*"],
        route_configuration=ForwardingConfiguration(
            forwarding_protocol="HttpsOnly",
            backend_pool=SubResource(
                id=f"/subscriptions/{clients.subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Network/frontDoors/{name}/backendPools/{backend_pool_name}"
            ),
        ),
        enabled_state="Enabled",
    )

    front_door = FrontDoor(
        location="global",
        frontend_endpoints=[frontend_endpoint],
        backend_pools=[backend_pool],
        health_probe_settings=[health_probe],
        load_balancing_settings=[load_balancing],
        routing_rules=[routing_rule],
        enabled_state="Enabled",
        tags=tags or {},
    )

    poller = await clients.run(
        fd_client.front_doors.begin_create_or_update,
        resource_group,
        name,
        front_door,
    )

    result = await clients.run(poller.result)
    return "created", result.as_dict()


async def create_waf_policy(
    *,
    clients: Clients,
    resource_group: str,
    name: str,
    mode: str = "Prevention",
    custom_rules: list[dict[str, Any]] | None = None,
    managed_rules: list[dict[str, Any]] | None = None,
    tags: dict[str, str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[str, object]:
    if not validate_name("generic", name):
        return "error", {"message": "invalid waf policy name"}

    if dry_run:
        return "plan", {
            "name": name,
            "resource_group": resource_group,
            "mode": mode,
            "custom_rules": custom_rules or [],
            "managed_rules": managed_rules or [],
            "tags": tags or {},
        }

    from azure.mgmt.frontdoor import FrontDoorManagementClient
    from azure.mgmt.frontdoor.models import (
        CustomRule,
        CustomRuleList,
        ManagedRuleSet,
        ManagedRuleSetList,
        PolicySettings,
        WebApplicationFirewallPolicy,
    )

    fd_client = FrontDoorManagementClient(clients.cred, clients.subscription_id)

    try:
        existing = await clients.run(fd_client.policies.get, resource_group, name)
        if existing and not force:
            return "exists", existing.as_dict()
    except Exception:
        pass

    policy_settings = PolicySettings(
        enabled_state="Enabled",
        mode=mode,
        custom_block_response_status_code=403,
        custom_block_response_body="You are blocked by WAF",
    )

    managed_rule_sets: list[ManagedRuleSet] = []
    if not managed_rules:
        managed_rule_sets.append(
            ManagedRuleSet(
                rule_set_type="DefaultRuleSet",
                rule_set_version="1.0",
            )
        )
    else:
        for rule in managed_rules:
            managed_rule_sets.append(
                ManagedRuleSet(
                    rule_set_type=rule.get("type", "DefaultRuleSet"),
                    rule_set_version=rule.get("version", "1.0"),
                    rule_group_overrides=rule.get("overrides"),
                )
            )

    prepared_custom_rules: list[CustomRule] | None = None
    if custom_rules:
        prepared_custom_rules = [CustomRule(**r) for r in custom_rules]

    waf_policy = WebApplicationFirewallPolicy(
        location="global",
        policy_settings=policy_settings,
        custom_rules=(
            CustomRuleList(rules=prepared_custom_rules) if prepared_custom_rules else None
        ),
        managed_rules=ManagedRuleSetList(managed_rule_sets=managed_rule_sets),
        tags=tags or {},
    )

    poller = await clients.run(
        fd_client.policies.begin_create_or_update,
        resource_group,
        name,
        waf_policy,
    )
    result = await clients.run(poller.result)

    return "created", result.as_dict()
