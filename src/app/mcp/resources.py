from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.subscription import SubscriptionClient

from app.core.azure_auth import build_credential


class ResourceManager:
    def __init__(self) -> None:
        self._credential = build_credential()
        self._clients: dict[str, Any] = {}

    def _get_subscription_client(self) -> SubscriptionClient:
        if "subscription" not in self._clients:
            self._clients["subscription"] = SubscriptionClient(self._credential)
        return self._clients["subscription"]

    def _get_resource_client(
        self,
        subscription_id: str,
    ) -> ResourceManagementClient:
        key = f"resource_{subscription_id}"
        if key not in self._clients:
            self._clients[key] = ResourceManagementClient(
                self._credential,
                subscription_id,
            )
        return self._clients[key]

    async def list_subscriptions(self) -> list[dict[str, Any]]:
        client = self._get_subscription_client()
        subscriptions = await asyncio.to_thread(lambda: list(client.subscriptions.list()))
        return [
            {
                "id": sub.subscription_id,
                "name": sub.display_name,
                "state": sub.state,
                "tenant_id": getattr(sub, "tenant_id", None),
            }
            for sub in subscriptions
        ]

    async def get_subscription_resources(
        self,
        subscription_id: str,
    ) -> dict[str, Any]:
        client = self._get_resource_client(subscription_id)
        resources = await asyncio.to_thread(lambda: list(client.resources.list()))
        grouped: dict[str, list[dict[str, Any]]] = {}
        for resource in resources:
            resource_type = resource.type
            if resource_type not in grouped:
                grouped[resource_type] = []
            grouped[resource_type].append(
                {
                    "id": resource.id,
                    "name": resource.name,
                    "location": resource.location,
                    "tags": resource.tags or {},
                    "kind": resource.kind,
                }
            )
        return {
            "subscription_id": subscription_id,
            "total_resources": len(resources),
            "resources_by_type": grouped,
        }

    async def get_subscription_costs(
        self,
        subscription_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, Any]:
        from app.tools.finops.analyzer import CostManagementSystem

        cms = CostManagementSystem()
        analysis = await cms.analyze_costs(
            subscription_id,
            start_date,
            end_date,
        )
        return {
            "subscription_id": subscription_id,
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "total_cost": analysis.get("total_cost", 0),
            "breakdown_by_category": analysis.get(
                "breakdown_by_category",
                {},
            ),
            "top_resources": analysis.get(
                "top_expensive_resources",
                [],
            )[:5],
            "optimization_potential": analysis.get(
                "optimization_potential",
                0,
            ),
        }

    async def get_deployment_template(
        self,
        product: str,
        environment: str,
    ) -> dict[str, Any]:
        templates = {
            "web_app": {
                "resource_group": f"{product}-{environment}-rg",
                "location": "westeurope",
                "app_service_plan": {
                    "name": f"{product}-{environment}-plan",
                    "sku": "P1v3" if environment == "prod" else "B1",
                },
                "web_app": {
                    "name": f"{product}-{environment}-app",
                    "runtime": "PYTHON|3.11",
                },
            },
            "storage_account": {
                "resource_group": f"{product}-{environment}-rg",
                "location": "westeurope",
                "storage": {
                    "name": f"{product}{environment}storage",
                    "sku": ("Standard_GRS" if environment == "prod" else "Standard_LRS"),
                    "access_tier": "Hot",
                },
            },
        }
        return templates.get(product, {})

    async def get_active_deployments(self) -> list[dict[str, Any]]:
        return []
