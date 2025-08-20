from __future__ import annotations

import asyncio
from typing import Any, TypedDict, cast

from azure.core.exceptions import AzureError
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

from app.core.azure_auth import build_credential
from app.core.exceptions import ExternalServiceException, retry_on_error


class ResourceGroupInfo(TypedDict):
    name: str
    location: str
    tags: dict[str, str]


class ResourceDiscoveryService:
    def __init__(self) -> None:
        self._credential = build_credential()
        self._clients: dict[str, Any] = {}
        self._cache: dict[str, tuple[list[dict[str, Any]], float]] = {}
        self._cache_ttl = 300.0

    def _get_resource_client(self, subscription_id: str) -> ResourceManagementClient:
        key = f"resource_{subscription_id}"
        if key not in self._clients:
            self._clients[key] = ResourceManagementClient(self._credential, subscription_id)
        return self._clients[key]

    def _get_graph_client(self) -> ResourceGraphClient:
        if "graph" not in self._clients:
            self._clients["graph"] = ResourceGraphClient(self._credential)
        return self._clients["graph"]

    @retry_on_error(max_retries=3, delay=1.0, exceptions=(AzureError,))
    async def discover_resources(
        self,
        subscription_id: str,
        resource_group: str | None = None,
        resource_type: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        import time

        cache_key = f"{subscription_id}:{resource_group}:{resource_type}:{str(tags)}"
        if cache_key in self._cache:
            cached_data, cached_time = self._cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return cached_data
        query = self._build_kql_query(subscription_id, resource_group, resource_type, tags)
        resources = await self._execute_graph_query(query, [subscription_id])
        self._cache[cache_key] = (resources, time.time())
        return resources

    async def get_resource_details(
        self,
        subscription_id: str,
        resource_id: str,
    ) -> dict[str, Any]:
        client = self._get_resource_client(subscription_id)
        try:
            resource = await asyncio.to_thread(
                client.resources.get_by_id, resource_id, api_version="2023-07-01"
            )
            return {
                "id": resource.id,
                "name": resource.name,
                "type": resource.type,
                "location": resource.location,
                "tags": resource.tags or {},
                "properties": resource.properties or {},
                "sku": getattr(resource, "sku", None),
                "kind": getattr(resource, "kind", None),
                "managed_by": getattr(resource, "managed_by", None),
            }
        except AzureError as e:
            raise ExternalServiceException(f"Failed to get resource details: {e}") from e

    async def list_resource_groups(
        self,
        subscription_id: str,
    ) -> list[ResourceGroupInfo]:
        client = self._get_resource_client(subscription_id)
        try:
            groups = await asyncio.to_thread(lambda: list(client.resource_groups.list()))
            return [
                {
                    "name": rg.name,
                    "location": rg.location,
                    "tags": (
                        cast(dict[str, str], rg.tags) if rg.tags is not None else dict[str, str]()
                    ),
                }
                for rg in groups
            ]
        except AzureError as e:
            raise ExternalServiceException(f"Failed to list resource groups: {e}") from e

    async def get_resource_metrics(
        self,
        subscription_id: str,
        resource_id: str,
        metric_names: list[str],
        timespan: str = "PT1H",
    ) -> dict[str, Any]:
        from azure.mgmt.monitor import MonitorManagementClient

        if "monitor" not in self._clients:
            self._clients["monitor"] = MonitorManagementClient(self._credential, subscription_id)
        monitor_client = self._clients["monitor"]
        try:
            metrics = await asyncio.to_thread(
                monitor_client.metrics.list,
                resource_id,
                timespan=timespan,
                metricnames=",".join(metric_names),
            )
            result: dict[str, list[dict[str, Any]]] = {}
            for metric in metrics.value:
                metric_data: list[dict[str, Any]] = []
                for ts in metric.timeseries:
                    for data_point in ts.data:
                        metric_data.append(
                            {
                                "timestamp": data_point.time_stamp.isoformat(),
                                "average": data_point.average,
                                "minimum": data_point.minimum,
                                "maximum": data_point.maximum,
                                "total": data_point.total,
                                "count": data_point.count,
                            }
                        )
                result[metric.name.value] = metric_data
            return result
        except AzureError as e:
            raise ExternalServiceException(f"Failed to get resource metrics: {e}") from e

    def _build_kql_query(
        self,
        subscription_id: str,
        resource_group: str | None,
        resource_type: str | None,
        tags: dict[str, str] | None,
    ) -> str:
        query_parts = ["Resources"]
        where_clauses: list[str] = []
        if resource_group:
            where_clauses.append(f"resourceGroup =~ '{resource_group}'")
        if resource_type:
            where_clauses.append(f"type =~ '{resource_type}'")
        if tags:
            for key, value in tags.items():
                where_clauses.append(f"tags['{key}'] =~ '{value}'")
        if where_clauses:
            query_parts.append(f"| where {' and '.join(where_clauses)}")
        query_parts.append(
            "| project id, name, type, location, resourceGroup, tags, properties, sku, kind"
        )
        return "\n".join(query_parts)

    async def _execute_graph_query(
        self,
        query: str,
        subscriptions: list[str],
        skip: int = 0,
        max_results: int = 1000,
    ) -> list[dict[str, Any]]:
        client = self._get_graph_client()
        all_results: list[dict[str, Any]] = []
        skip_token: str | None = None
        while True:
            request = QueryRequest(
                query=query,
                subscriptions=subscriptions,
                options=QueryRequestOptions(
                    top=min(max_results - len(all_results), 1000),
                    skip=skip if not skip_token else None,
                    skip_token=skip_token,
                ),
            )
            try:
                result = await asyncio.to_thread(client.resources, request)
                all_results.extend(result.data)
                if not result.skip_token or len(all_results) >= max_results:
                    break
                skip_token = result.skip_token
            except AzureError as e:
                raise ExternalServiceException(f"Failed to execute graph query: {e}") from e
        return all_results

    async def get_resource_dependencies(
        self,
        subscription_id: str,
        resource_id: str,
    ) -> dict[str, list[str]]:
        query = f"""
        Resources
        | where id =~ '{resource_id}'
        | project id, dependencies = properties.dependsOn
        | mvexpand dependencies
        | project dependency = tostring(dependencies)
        """
        results = await self._execute_graph_query(query, [subscription_id])
        dependencies = [r.get("dependency", "") for r in results if r.get("dependency")]
        query_dependents = f"""
        Resources
        | where properties contains '{resource_id}'
        | project id
        """
        dependent_results = await self._execute_graph_query(query_dependents, [subscription_id])
        dependents = [r.get("id", "") for r in dependent_results if r.get("id")]
        return {
            "dependencies": dependencies,
            "dependents": dependents,
        }

    async def batch_get_resources(
        self,
        subscription_id: str,
        resource_ids: list[str],
        batch_size: int = 50,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for i in range(0, len(resource_ids), batch_size):
            batch = resource_ids[i : i + batch_size]
            batch_query = " or ".join([f"id =~ '{rid}'" for rid in batch])
            query = f"""
            Resources
            | where {batch_query}
            | project id, name, type, location, resourceGroup, tags, properties, sku, kind
            """
            batch_results = await self._execute_graph_query(query, [subscription_id])
            results.extend(batch_results)
            if i + batch_size < len(resource_ids):
                await asyncio.sleep(0.1)
        return results
