from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, TypedDict, cast

import structlog
from azure.core.exceptions import AzureError
from azure.mgmt.monitor import MonitorManagementClient
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
from opentelemetry import trace

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
        self._tracer = trace.get_tracer("finops.resource_discovery")
        self._log = structlog.get_logger()

    def _get_resource_client(self, subscription_id: str) -> ResourceManagementClient:
        key = f"resource_{subscription_id}"
        if key not in self._clients:
            self._clients[key] = ResourceManagementClient(self._credential, subscription_id)
        return cast("ResourceManagementClient", self._clients[key])

    def _get_graph_client(self) -> ResourceGraphClient:
        if "graph" not in self._clients:
            self._clients["graph"] = ResourceGraphClient(self._credential)
        return cast("ResourceGraphClient", self._clients["graph"])

    def _get_monitor_client(self, subscription_id: str) -> MonitorManagementClient:
        key = f"monitor_{subscription_id}"
        if key not in self._clients:
            self._clients[key] = MonitorManagementClient(self._credential, subscription_id)
        return cast("MonitorManagementClient", self._clients[key])

    def _normalize_tags(self, tags: Any) -> dict[str, str]:
        if isinstance(tags, dict):
            return {str(k): str(v) for k, v in tags.items() if k is not None}
        return {}

    def _iso_or_now(self, dt: Any) -> str:
        if isinstance(dt, datetime):
            return dt.isoformat()
        try:
            # type: ignore[redundant-cast]
            return cast("datetime", dt).isoformat()
        except Exception:
            return datetime.utcnow().isoformat()

    @retry_on_error(max_retries=3, base_delay=1.0, exceptions=(AzureError,))
    async def discover_resources(
        self,
        subscription_id: str,
        resource_group: str | None = None,
        resource_type: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        cache_key = f"{subscription_id}:{resource_group}:{resource_type}:{tags!s}"
        cached = self._cache.get(cache_key)
        if cached:
            data, ts = cached
            if time.time() - ts < self._cache_ttl:
                return data
        query = self._build_kql_query(subscription_id, resource_group, resource_type, tags)
        with self._tracer.start_as_current_span("resource_discovery.discover_resources") as span:
            span.set_attribute("azure.subscription_id", subscription_id)
            if resource_group:
                span.set_attribute("azure.resource_group", resource_group)
            if resource_type:
                span.set_attribute("azure.resource_type", resource_type)
            try:
                resources = await self._execute_graph_query(query, [subscription_id])
                self._cache[cache_key] = (resources, time.time())
                self._log.info(
                    "finops.resources.discovered",
                    subscription_id=subscription_id,
                    count=len(resources),
                    resource_group=resource_group,
                    resource_type=resource_type,
                )
                return resources
            except ExternalServiceException as err:
                current = trace.get_current_span()
                if current:
                    current.record_exception(err)
                raise

    async def get_resource_details(
        self,
        subscription_id: str,
        resource_id: str,
    ) -> dict[str, Any]:
        client = self._get_resource_client(subscription_id)
        with self._tracer.start_as_current_span("resource_discovery.get_resource_details") as span:
            span.set_attribute("azure.subscription_id", subscription_id)
            span.set_attribute("azure.resource_id", resource_id)
            try:
                resource = await asyncio.to_thread(
                    client.resources.get_by_id, resource_id, api_version="2023-07-01"
                )
                data: dict[str, Any] = {
                    "id": resource.id,
                    "name": resource.name,
                    "type": resource.type,
                    "location": resource.location,
                    "tags": self._normalize_tags(getattr(resource, "tags", None)),
                    "properties": getattr(resource, "properties", {}) or {},
                    "sku": getattr(resource, "sku", None),
                    "kind": getattr(resource, "kind", None),
                    "managed_by": getattr(resource, "managed_by", None),
                }
                self._log.info(
                    "finops.resource.details",
                    subscription_id=subscription_id,
                    resource_id=resource_id,
                    resource_type=data.get("type", ""),
                    location=data.get("location", ""),
                )
                return data
            except AzureError as e:
                err = ExternalServiceException(f"Failed to get resource details: {e}")
                current = trace.get_current_span()
                if current:
                    current.record_exception(err)
                raise err from e

    async def list_resource_groups(
        self,
        subscription_id: str,
    ) -> list[ResourceGroupInfo]:
        client = self._get_resource_client(subscription_id)
        with self._tracer.start_as_current_span("resource_discovery.list_resource_groups") as span:
            span.set_attribute("azure.subscription_id", subscription_id)
            try:
                groups = await asyncio.to_thread(lambda: list(client.resource_groups.list()))
                result: list[ResourceGroupInfo] = [
                    ResourceGroupInfo(
                        name=rg.name,
                        location=rg.location,
                        tags=self._normalize_tags(getattr(rg, "tags", None)),
                    )
                    for rg in groups
                ]
                self._log.info(
                    "finops.resource_groups.listed",
                    subscription_id=subscription_id,
                    count=len(result),
                )
                return result
            except AzureError as e:
                err = ExternalServiceException(f"Failed to list resource groups: {e}")
                current = trace.get_current_span()
                if current:
                    current.record_exception(err)
                raise err from e

    async def get_resource_metrics(
        self,
        subscription_id: str,
        resource_id: str,
        metric_names: list[str],
        timespan: str = "PT1H",
    ) -> dict[str, Any]:
        monitor_client = self._get_monitor_client(subscription_id)
        with self._tracer.start_as_current_span("resource_discovery.get_resource_metrics") as span:
            span.set_attribute("azure.subscription_id", subscription_id)
            span.set_attribute("azure.resource_id", resource_id)
            span.set_attribute("azure.metrics.count", len(metric_names))
            try:
                metrics = await asyncio.to_thread(
                    monitor_client.metrics.list,
                    resource_id,
                    timespan=timespan,
                    metricnames=",".join(metric_names),
                )
                result: dict[str, list[dict[str, Any]]] = {}
                values = getattr(metrics, "value", None) or []
                for metric in values:
                    metric_data: list[dict[str, Any]] = []
                    timeseries = getattr(metric, "timeseries", None) or []
                    for ts in timeseries:
                        datapoints = getattr(ts, "data", None) or []
                        for data_point in datapoints:
                            metric_data.append(
                                {
                                    "timestamp": self._iso_or_now(
                                        getattr(data_point, "time_stamp", None)
                                    ),
                                    "average": getattr(data_point, "average", None),
                                    "minimum": getattr(data_point, "minimum", None),
                                    "maximum": getattr(data_point, "maximum", None),
                                    "total": getattr(data_point, "total", None),
                                    "count": getattr(data_point, "count", None),
                                }
                            )
                    name_obj = getattr(metric, "name", None)
                    metric_name = getattr(name_obj, "value", None) or "unknown"
                    result[metric_name] = metric_data
                self._log.info(
                    "finops.metrics.fetched",
                    subscription_id=subscription_id,
                    resource_id=resource_id,
                    metrics=list(result.keys()),
                )
                return result
            except AzureError as e:
                err = ExternalServiceException(f"Failed to get resource metrics: {e}")
                current = trace.get_current_span()
                if current:
                    current.record_exception(err)
                raise err from e

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
        with self._tracer.start_as_current_span("resource_discovery._execute_graph_query") as span:
            span.set_attribute("azure.subscriptions.count", len(subscriptions))
            span.set_attribute("azure.graph.max_results", max_results)
            while True:
                top = min(max_results - len(all_results), 1000)
                if top <= 0:
                    break
                request = QueryRequest(
                    query=query,
                    subscriptions=subscriptions,
                    options=QueryRequestOptions(
                        top=top,
                        skip=None if skip_token else skip,
                        skip_token=skip_token,
                    ),
                )
                try:
                    result = await asyncio.to_thread(client.resources, request)
                    data = getattr(result, "data", None) or []
                    all_results.extend(cast("list[dict[str, Any]]", data))
                    token = getattr(result, "skip_token", None)
                    if not token or len(all_results) >= max_results:
                        break
                    skip_token = cast("str | None", token)
                except AzureError as e:
                    err = ExternalServiceException(f"Failed to execute graph query: {e}")
                    current = trace.get_current_span()
                    if current:
                        current.record_exception(err)
                    raise err from e
        self._log.info(
            "finops.graph.query.executed",
            subscriptions=subscriptions,
            returned=len(all_results),
        )
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
        with self._tracer.start_as_current_span(
            "resource_discovery.get_resource_dependencies"
        ) as span:
            span.set_attribute("azure.subscription_id", subscription_id)
            span.set_attribute("azure.resource_id", resource_id)
            deps_results = await self._execute_graph_query(query, [subscription_id])
            dependencies = [r.get("dependency", "") for r in deps_results if r.get("dependency")]
            query_dependents = f"""
            Resources
            | where properties contains '{resource_id}'
            | project id
            """
            dependents_results = await self._execute_graph_query(
                query_dependents, [subscription_id]
            )
            dependents = [r.get("id", "") for r in dependents_results if r.get("id")]
            self._log.info(
                "finops.resource.dependencies",
                subscription_id=subscription_id,
                resource_id=resource_id,
                dependencies=len(dependencies),
                dependents=len(dependents),
            )
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
        with self._tracer.start_as_current_span("resource_discovery.batch_get_resources") as span:
            span.set_attribute("azure.subscription_id", subscription_id)
            span.set_attribute("azure.batch.size", batch_size)
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
            self._log.info(
                "finops.resources.batch_fetched",
                subscription_id=subscription_id,
                requested=len(resource_ids),
                returned=len(results),
            )
            return results
