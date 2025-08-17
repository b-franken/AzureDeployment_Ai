from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict


class StorageSkuPricing(TypedDict):
    per_gb: float
    transactions: float


class CosmosPricing(TypedDict):
    per_ru: float
    storage_per_gb: float


class KeyVaultPricing(TypedDict):
    operations: float
    storage: float


class PricingData(TypedDict):
    web_stack: Mapping[str, float]
    storage_account: Mapping[str, StorageSkuPricing]
    aks_cluster: Mapping[str, float]
    sql_server: Mapping[str, float]
    redis: Mapping[str, float]
    cosmos_account: CosmosPricing
    key_vault: KeyVaultPricing


class CostEstimator:
    def __init__(self) -> None:
        self.pricing_data: PricingData = {
            "web_stack": {"B1": 13.0, "B2": 26.0, "P1v3": 147.0, "P2v3": 294.0},
            "storage_account": {
                "Standard_LRS": {"per_gb": 0.02, "transactions": 0.0004},
                "Standard_ZRS": {"per_gb": 0.025, "transactions": 0.0004},
            },
            "aks_cluster": {
                "Standard_DS2_v2": 70.0,
                "Standard_DS3_v2": 140.0,
                "Standard_DS4_v2": 280.0,
            },
            "sql_server": {"S0": 15.0, "S1": 30.0, "P1": 465.0},
            "redis": {"Standard": 61.0, "Premium": 339.0},
            "cosmos_account": {"per_ru": 0.008, "storage_per_gb": 0.25},
            "key_vault": {"operations": 0.03, "storage": 0.026},
        }

    def estimate_monthly_cost(self, spec: dict[str, Any]) -> dict[str, Any]:
        total_cost = 0.0
        breakdown: list[dict[str, Any]] = []
        for resource in spec.get("resources", []):
            cost = self._estimate_resource_cost(resource)
            total_cost += float(cost.get("monthly_cost", 0.0))
            breakdown.append(cost)
        return {
            "total_monthly_cost": round(total_cost, 2),
            "currency": "USD",
            "breakdown": breakdown,
            "cost_optimization_suggestions": self._generate_suggestions(breakdown),
        }

    def _estimate_resource_cost(self, resource: dict[str, Any]) -> dict[str, Any]:
        resource_type = resource.get("type", "")
        if resource_type == "web_stack":
            return self._estimate_webapp_cost(resource)
        if resource_type == "storage_account":
            return self._estimate_storage_cost(resource)
        if resource_type == "aks_cluster":
            return self._estimate_aks_cost(resource)
        if resource_type == "sql_server":
            return self._estimate_sql_cost(resource)
        if resource_type == "redis":
            return self._estimate_redis_cost(resource)
        if resource_type == "cosmos_account":
            return self._estimate_cosmos_cost(resource)
        if resource_type == "key_vault":
            return self._estimate_keyvault_cost(resource)
        return {
            "resource_name": resource.get("name", "unknown"),
            "resource_type": resource_type,
            "monthly_cost": 0.0,
            "notes": "Cost estimation not available for this resource type",
        }

    def _estimate_webapp_cost(self, resource: dict[str, Any]) -> dict[str, Any]:
        plan = resource.get("plan", {})
        sku = plan.get("sku", "B1")
        capacity = int(plan.get("capacity", 1))
        base_cost_opt = self.pricing_data["web_stack"].get(sku)
        base_cost = base_cost_opt if base_cost_opt is not None else 13.0
        slots = len(resource.get("slots", []))
        total = base_cost * capacity + (slots * base_cost * 0.5)
        return {
            "resource_name": resource.get("name", ""),
            "resource_type": "web_stack",
            "monthly_cost": float(total),
            "details": {"sku": sku, "capacity": capacity, "slots": slots},
        }

    def _estimate_storage_cost(self, resource: dict[str, Any]) -> dict[str, Any]:
        sku = resource.get("sku", "Standard_LRS")
        estimated_gb = 100
        estimated_transactions = 100000
        pricing_opt = self.pricing_data["storage_account"].get(sku)
        if pricing_opt is None:
            pricing = self.pricing_data["storage_account"]["Standard_LRS"]
        else:
            pricing = pricing_opt
        storage_cost = estimated_gb * pricing["per_gb"]
        transaction_cost = (estimated_transactions / 10000) * pricing["transactions"]
        return {
            "resource_name": resource.get("name", ""),
            "resource_type": "storage_account",
            "monthly_cost": float(storage_cost + transaction_cost),
            "details": {
                "sku": sku,
                "estimated_gb": estimated_gb,
                "estimated_transactions": estimated_transactions,
            },
        }

    def _estimate_aks_cost(self, resource: dict[str, Any]) -> dict[str, Any]:
        node_pools = resource.get("node_pools", [])
        total_cost = 0.0
        details: list[dict[str, Any]] = []
        for pool in node_pools:
            vm_size = pool.get("vm_size", "Standard_DS2_v2")
            count = int(pool.get("count", 1))
            vm_cost_opt = self.pricing_data["aks_cluster"].get(vm_size)
            vm_cost = vm_cost_opt if vm_cost_opt is not None else 70.0
            pool_cost = vm_cost * count
            total_cost += pool_cost
            details.append(
                {
                    "pool": pool.get("name", "unknown"),
                    "vm_size": vm_size,
                    "count": count,
                    "monthly_cost": float(pool_cost),
                }
            )
        return {
            "resource_name": resource.get("name", ""),
            "resource_type": "aks_cluster",
            "monthly_cost": float(total_cost),
            "details": {"node_pools": details},
        }

    def _estimate_sql_cost(self, resource: dict[str, Any]) -> dict[str, Any]:
        databases = resource.get("databases", [])
        total_cost = 0.0
        for db in databases:
            sku = db.get("sku_name", "S0")
            db_cost_opt = self.pricing_data["sql_server"].get(sku)
            db_cost = db_cost_opt if db_cost_opt is not None else 15.0
            total_cost += db_cost
        return {
            "resource_name": resource.get("name", ""),
            "resource_type": "sql_server",
            "monthly_cost": float(total_cost),
            "details": {"databases": len(databases)},
        }

    def _estimate_redis_cost(self, resource: dict[str, Any]) -> dict[str, Any]:
        sku_name = resource.get("sku_name", "Standard")
        capacity = int(resource.get("capacity", 1))
        base_cost_opt = self.pricing_data["redis"].get(sku_name)
        base_cost = base_cost_opt if base_cost_opt is not None else 61.0
        return {
            "resource_name": resource.get("name", ""),
            "resource_type": "redis",
            "monthly_cost": float(base_cost * capacity),
            "details": {"sku": sku_name, "capacity": capacity},
        }

    def _estimate_cosmos_cost(self, resource: dict[str, Any]) -> dict[str, Any]:
        estimated_rus = 400
        estimated_storage_gb = 10
        locations = len(resource.get("locations", [{"location": "westeurope"}]))
        ru_cost = estimated_rus * self.pricing_data["cosmos_account"]["per_ru"] * 730 * locations
        storage_cost = (
            estimated_storage_gb * self.pricing_data["cosmos_account"]["storage_per_gb"] * locations
        )
        return {
            "resource_name": resource.get("name", ""),
            "resource_type": "cosmos_account",
            "monthly_cost": float(ru_cost + storage_cost),
            "details": {
                "estimated_rus": estimated_rus,
                "estimated_storage_gb": estimated_storage_gb,
                "locations": locations,
            },
        }

    def _estimate_keyvault_cost(self, resource: dict[str, Any]) -> dict[str, Any]:
        estimated_operations = 10000
        estimated_keys = 10
        operation_cost = (estimated_operations / 10000) * self.pricing_data["key_vault"][
            "operations"
        ]
        storage_cost = estimated_keys * self.pricing_data["key_vault"]["storage"]
        return {
            "resource_name": resource.get("name", ""),
            "resource_type": "key_vault",
            "monthly_cost": float(operation_cost + storage_cost),
            "details": {
                "estimated_operations": estimated_operations,
                "estimated_keys": estimated_keys,
            },
        }

    def _generate_suggestions(self, breakdown: list[dict[str, Any]]) -> list[str]:
        suggestions: list[str] = []
        for resource in breakdown:
            if resource.get("resource_type") == "web_stack":
                details = resource.get("details", {})
                if (
                    str(details.get("sku", "")).startswith("P")
                    and float(resource.get("monthly_cost", 0.0)) < 200
                ):
                    suggestions.append(
                        f"Consider downgrading {resource.get('resource_name', '')} "
                        "to B-series for dev/test"
                    )
            elif resource.get("resource_type") == "aks_cluster":
                if float(resource.get("monthly_cost", 0.0)) > 500:
                    suggestions.append(
                        f"Enable autoscaling for {resource.get('resource_name', '')} "
                        "to optimize costs"
                    )
            elif resource.get("resource_type") == "storage_account":
                details = resource.get("details", {})
                if "ZRS" in str(details.get("sku", "")):
                    suggestions.append(
                        f"Consider LRS for {resource.get('resource_name', '')} "
                        "in non-production environments"
                    )
        if not suggestions:
            suggestions.append("No immediate cost optimization opportunities identified")
        return suggestions
