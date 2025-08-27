from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.ai.nlu.unified_parser import UnifiedParseResult


class ResourceMapper:
    def __init__(self) -> None:
        self.resource_mappings: dict[
            str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
        ] = {
            "webapp": self._map_webapp,
            "storage": self._map_storage,
            "aks": self._map_aks,
            "sql": self._map_sql,
            "keyvault": self._map_keyvault,
            "vnet": self._map_vnet,
            "cosmos": self._map_cosmos,
            "redis": self._map_redis,
            "acr": self._map_acr,
        }

    def map_nlu_to_avm(self, nlu_result: UnifiedParseResult) -> dict[str, Any]:
        resource_type = nlu_result.resource_type or ""
        parameters = nlu_result.parameters or {}
        context = nlu_result.context or {}

        mapper = self.resource_mappings.get(resource_type)
        if not mapper:
            return self._map_generic(resource_type, parameters, context)

        return mapper(parameters, context)

    def _map_webapp(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        name: str = str(params.get("name", ""))
        environment: str = str(context.get("environment", "dev"))

        return {
            "type": "web_stack",
            "name": name,
            "plan": {
                "name": params.get("plan", f"{name}-{environment}-plan"),
                "sku": self._determine_sku(environment, params.get("sku")),
                "linux": params.get("runtime") is not None,
                "zone_redundant": environment == "prod",
                "capacity": self._determine_capacity(environment),
            },
            "site": {
                "kind": "app,linux" if params.get("runtime") else "app",
                "https_only": True,
                "always_on": environment != "dev",
                "min_tls_version": "1.2",
                "ftps_state": "Disabled",
                "health_check_path": params.get("health_check_path", "/health"),
                "app_settings": self._build_app_settings(params, environment),
            },
            "slots": self._build_slots(environment),
        }

    def _map_storage(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        environment: str = str(context.get("environment", "dev"))

        return {
            "type": "storage_account",
            "name": params.get("name", ""),
            "sku": self._determine_storage_sku(environment, params.get("sku")),
            "kind": "StorageV2",
            "public_network_access": "Disabled" if environment == "prod" else "Enabled",
            "allow_blob_public_access": False,
            "min_tls_version": "TLS1_2",
        }

    def _map_aks(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        name: str = str(params.get("name", ""))
        environment: str = str(context.get("environment", "dev"))

        return {
            "type": "aks_cluster",
            "name": name,
            "dns_prefix": params.get("dns_prefix", f"{name}-{environment}"),
            "node_pools": [
                {
                    "name": "system",
                    "count": self._determine_node_count(environment, "system"),
                    "vm_size": self._determine_vm_size(environment, "system"),
                    "mode": "System",
                },
                {
                    "name": "user",
                    "count": self._determine_node_count(environment, "user"),
                    "vm_size": self._determine_vm_size(environment, "user"),
                    "mode": "User",
                },
            ],
            "network_profile": {
                "network_plugin": "azure",
                "network_policy": "azure",
                "service_cidr": "10.0.0.0/16",
                "dns_service_ip": "10.0.0.10",
            },
            "addons": {
                "azure_policy": True,
                "monitoring": True,
                "ingress": environment == "prod",
            },
        }

    def _map_sql(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        environment: str = str(context.get("environment", "dev"))
        server_name: str = str(params.get("server_name") or params.get("name", ""))

        return {
            "type": "sql_server",
            "name": server_name,
            "version": "12.0",
            "administrator_login": params.get("sql_admin_user", "sqladmin"),
            "administrator_password": params.get("sql_admin_password", ""),
            "minimal_tls_version": "1.2",
            "public_network_access": "Disabled" if environment == "prod" else "Enabled",
            "databases": [
                {
                    "name": params.get("db_name", f"{server_name}-db"),
                    "sku_name": self._determine_sql_sku(environment),
                    "max_size_gb": self._determine_sql_size(environment),
                    "zone_redundant": environment == "prod",
                }
            ],
        }

    def _map_keyvault(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        environment: str = str(context.get("environment", "dev"))
        return {
            "type": "key_vault",
            "name": params.get("vault_name") or params.get("name", ""),
            "enable_rbac": True,
            "purge_protection": environment == "prod",
            "soft_delete_retention_in_days": 90 if environment == "prod" else 7,
        }

    def _map_vnet(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        environment: str = str(context.get("environment", "dev"))

        return {
            "type": "vnet",
            "name": params.get("name", ""),
            "address_prefixes": [params.get("address_prefix", "10.0.0.0/16")],
            "subnets": self._build_subnets(environment),
        }

    def _map_cosmos(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        environment: str = str(context.get("environment", "dev"))
        return {
            "type": "cosmos_account",
            "name": params.get("account_name") or params.get("name", ""),
            "kind": params.get("kind", "GlobalDocumentDB"),
            "consistency_level": "Session",
            "enable_automatic_failover": environment == "prod",
            "locations": self._determine_cosmos_locations(environment),
        }

    def _map_redis(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        environment: str = str(context.get("environment", "dev"))

        return {
            "type": "redis",
            "name": params.get("name", ""),
            "sku_name": "Premium" if environment == "prod" else "Standard",
            "capacity": 1 if environment != "prod" else 2,
            "enable_non_ssl_port": False,
            "minimum_tls_version": "1.2",
        }

    def _map_acr(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        environment: str = str(context.get("environment", "dev"))

        return {
            "type": "container_registry",
            "name": params.get("name", ""),
            "sku": "Premium" if environment == "prod" else "Basic",
            "admin_user_enabled": environment != "prod",
            "network_rule_set": {
                "default_action": "Deny" if environment == "prod" else "Allow",
            },
        }

    def _map_generic(
        self, resource_type: str, params: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "type": resource_type,
            "name": params.get("name", ""),
            "location": context.get("location", "westeurope"),
            "tags": context.get("tags", {}),
        }

    def _determine_sku(self, environment: str, requested_sku: str | None) -> str:
        if requested_sku:
            return requested_sku
        sku_map = {
            "dev": "B1",
            "test": "B2",
            "staging": "P1v3",
            "prod": "P2v3",
        }
        return sku_map.get(environment, "B1")

    def _determine_storage_sku(self, environment: str, requested_sku: str | None) -> str:
        if requested_sku:
            return requested_sku
        return "Standard_ZRS" if environment == "prod" else "Standard_LRS"

    def _determine_capacity(self, environment: str) -> int:
        capacity_map = {
            "dev": 1,
            "test": 1,
            "staging": 2,
            "prod": 3,
        }
        return capacity_map.get(environment, 1)

    def _determine_node_count(self, environment: str, pool_type: str) -> int:
        if pool_type == "system":
            return 3 if environment == "prod" else 1
        return 5 if environment == "prod" else 2

    def _determine_vm_size(self, environment: str, pool_type: str) -> str:
        if pool_type == "system":
            return "Standard_DS2_v2"
        return "Standard_DS4_v2" if environment == "prod" else "Standard_DS3_v2"

    def _determine_sql_sku(self, environment: str) -> str:
        return "P1" if environment == "prod" else "S0"

    def _determine_sql_size(self, environment: str) -> int:
        return 500 if environment == "prod" else 10

    def _determine_cosmos_locations(self, environment: str) -> list[dict[str, Any]]:
        if environment == "prod":
            return [
                {"location": "westeurope", "failover_priority": 0},
                {"location": "northeurope", "failover_priority": 1},
            ]
        return [{"location": "westeurope", "failover_priority": 0}]

    def _build_app_settings(self, params: dict[str, Any], environment: str) -> dict[str, str]:
        settings: dict[str, str] = {
            "ENVIRONMENT": environment,
            "APPLICATION_INSIGHTS_ENABLED": "true",
        }
        if params.get("app_settings"):
            for k, v in params["app_settings"].items():
                settings[str(k)] = str(v)
        return settings

    def _build_slots(self, environment: str) -> list[dict[str, Any]]:
        if environment in ["staging", "prod"]:
            return [
                {
                    "name": "staging",
                    "always_on": True,
                    "min_tls_version": "1.2",
                    "app_settings": {
                        "ENVIRONMENT": "staging",
                        "SLOT_NAME": "staging",
                    },
                }
            ]
        return []

    def _build_subnets(self, environment: str) -> list[dict[str, Any]]:
        base_subnets: list[dict[str, Any]] = [
            {
                "name": "default",
                "address_prefix": "10.0.1.0/24",
                "privateEndpointNetworkPolicies": "Disabled",
            },
            {
                "name": "aks",
                "address_prefix": "10.0.2.0/24",
                "privateEndpointNetworkPolicies": "Enabled",
            },
        ]
        if environment == "prod":
            base_subnets.extend(
                [
                    {
                        "name": "gateway",
                        "address_prefix": "10.0.3.0/24",
                        "privateEndpointNetworkPolicies": "Enabled",
                    },
                    {
                        "name": "private-endpoints",
                        "address_prefix": "10.0.4.0/24",
                        "privateEndpointNetworkPolicies": "Disabled",
                    },
                ]
            )
        return base_subnets
