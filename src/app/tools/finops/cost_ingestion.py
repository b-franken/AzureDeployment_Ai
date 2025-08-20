from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta
from typing import Any, NotRequired, TypedDict, cast

from azure.core.exceptions import AzureError
from azure.mgmt.consumption import ConsumptionManagementClient
from azure.mgmt.consumption.models import Budget, BudgetTimePeriod
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
    Export,
    ExportDefinition,
    ExportDeliveryDestination,
    ExportDeliveryInfo,
    ExportRecurrencePeriod,
    ExportSchedule,
    ForecastAggregation,
    ForecastDataset,
    ForecastDefinition,
    ForecastTimeframe,
    ForecastTimePeriod,
    QueryAggregation,
    QueryComparisonExpression,
    QueryDataset,
    QueryDefinition,
    QueryFilter,
    QueryGrouping,
    QueryTimePeriod,
    TimeframeType,
)

from app.core.azure_auth import build_credential
from app.core.exceptions import ExternalServiceException, retry_on_error


class ResourceCost(TypedDict, total=False):
    cost: float
    cost_usd: float
    currency: str
    error: NotRequired[str]


def _to_iso(value: Any) -> str | None:
    if isinstance(value, (datetime | date)):
        return value.isoformat()
    return None


def _extract_subscription_id(scope: str | None) -> str | None:
    if not scope:
        return None
    m = re.match(r"^/subscriptions/([^/]+)", scope, flags=re.IGNORECASE)
    return m.group(1) if m else None


class CostIngestionService:
    def __init__(self, subscription_id: str | None = None) -> None:
        self._credential = build_credential()
        self._subscription_id: str | None = subscription_id
        self._cost_client: CostManagementClient | None = None
        self._consumption_client: ConsumptionManagementClient | None = None
        self._consumption_client_sub_id: str | None = None
        self._cache: dict[str, tuple[Any, float]] = {}
        self._cache_ttl: float = 3600.0

    def _get_cost_client(self) -> CostManagementClient:
        if self._cost_client is None:
            self._cost_client = CostManagementClient(self._credential)
        return self._cost_client

    def _get_consumption_client(self, scope: str | None = None) -> ConsumptionManagementClient:
        sub_id = self._subscription_id or _extract_subscription_id(scope)
        if not sub_id:
            raise ExternalServiceException(
                "subscription_id is required to use the ConsumptionManagementClient"
            )
        if self._consumption_client is None or self._consumption_client_sub_id != sub_id:
            self._consumption_client = ConsumptionManagementClient(self._credential, sub_id)
            self._consumption_client_sub_id = sub_id
        return self._consumption_client

    @retry_on_error(max_retries=3, delay=1.0, exceptions=(AzureError,))
    async def get_usage_details(
        self,
        scope: str,
        start_date: datetime,
        end_date: datetime,
        granularity: str = "Daily",
        group_by: list[str] | None = None,
        filter_expression: str | None = None,
    ) -> list[dict[str, Any]]:
        import time

        cache_key = (
            f"usage:{scope}:{start_date}:{end_date}:{granularity}:{group_by}:{filter_expression}"
        )
        if cache_key in self._cache:
            cached_data, cached_time = self._cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return cached_data
        client = self._get_cost_client()
        dataset = QueryDataset(
            granularity=granularity,
            aggregation={
                "totalCost": QueryAggregation(name="PreTaxCost", function="Sum"),
                "totalCostUSD": QueryAggregation(name="PreTaxCostUSD", function="Sum"),
            },
        )
        if group_by:
            dataset.grouping = [QueryGrouping(type="Dimension", name=dim) for dim in group_by]
        if filter_expression:
            dataset.filter = QueryFilter(
                dimensions=QueryComparisonExpression(
                    name="ResourceType",
                    operator="In",
                    values=[filter_expression],
                )
            )
        query_def = QueryDefinition(
            type="Usage",
            timeframe=TimeframeType.CUSTOM,
            time_period=QueryTimePeriod(from_property=start_date, to=end_date),
            dataset=dataset,
        )
        try:
            result = await asyncio.to_thread(client.query.usage, scope, query_def)
            usage_data: list[dict[str, Any]] = []
            if result and result.rows:
                columns: list[str] = []
                if result.columns:
                    for i, col in enumerate(result.columns):
                        name = getattr(col, "name", None)
                        columns.append(name if isinstance(name, str) and name else f"col_{i}")
                for row in result.rows:
                    usage_data.append(dict(zip(columns, row, strict=False)))
            self._cache[cache_key] = (usage_data, time.time())
            return usage_data
        except AzureError as e:
            raise ExternalServiceException(f"Failed to get usage details: {e}") from e

    async def get_resource_costs(
        self,
        scope: str,
        resource_ids: list[str],
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, ResourceCost]:
        client = self._get_cost_client()
        resource_costs: dict[str, ResourceCost] = {}
        for resource_id in resource_ids:
            dataset = QueryDataset(
                granularity="None",
                aggregation={
                    "totalCost": QueryAggregation(name="PreTaxCost", function="Sum"),
                    "totalCostUSD": QueryAggregation(name="PreTaxCostUSD", function="Sum"),
                },
                filter=QueryFilter(
                    dimensions=QueryComparisonExpression(
                        name="ResourceId",
                        operator="In",
                        values=[resource_id],
                    )
                ),
            )
            query_def = QueryDefinition(
                type="ActualCost",
                timeframe=TimeframeType.CUSTOM,
                time_period=QueryTimePeriod(from_property=start_date, to=end_date),
                dataset=dataset,
            )
            try:
                result = await asyncio.to_thread(client.query.usage, scope, query_def)
                if result and result.rows and len(result.rows) > 0:
                    cost_row = result.rows[0]
                    resource_costs[resource_id] = {
                        "cost": float(cost_row[0]) if len(cost_row) > 0 else 0.0,
                        "cost_usd": float(cost_row[1]) if len(cost_row) > 1 else 0.0,
                        "currency": "USD",
                    }
                else:
                    resource_costs[resource_id] = {
                        "cost": 0.0,
                        "cost_usd": 0.0,
                        "currency": "USD",
                    }
            except AzureError:
                resource_costs[resource_id] = {
                    "cost": 0.0,
                    "cost_usd": 0.0,
                    "currency": "USD",
                    "error": "Failed to retrieve cost",
                }
            await asyncio.sleep(0.1)
        return resource_costs

    async def get_forecast(
        self,
        scope: str,
        granularity: str = "Daily",
        metric: str = "PreTaxCost",
        forecast_days: int = 30,
    ) -> list[dict[str, Any]]:
        client = self._get_cost_client()
        forecast_def = ForecastDefinition(
            type="Usage",
            timeframe=ForecastTimeframe.CUSTOM,
            time_period=ForecastTimePeriod(
                from_property=datetime.utcnow(),
                to=datetime.utcnow() + timedelta(days=forecast_days),
            ),
            dataset=ForecastDataset(
                granularity=granularity,
                aggregation={
                    "totalCost": ForecastAggregation(name=metric, function="Sum"),
                },
            ),
            include_actual_cost=False,
            include_fresh_partial_cost=False,
        )
        try:
            result = await asyncio.to_thread(client.forecast.usage, scope, forecast_def)
            forecast_data: list[dict[str, Any]] = []
            if result and result.rows:
                columns: list[str] = []
                if result.columns:
                    for i, col in enumerate(result.columns):
                        name = getattr(col, "name", None)
                        columns.append(name if isinstance(name, str) and name else f"col_{i}")
                for row in result.rows:
                    forecast_data.append(dict(zip(columns, row, strict=False)))
            return forecast_data
        except AzureError as e:
            raise ExternalServiceException(f"Failed to get forecast: {e}") from e

    async def get_budgets(self, scope: str) -> list[dict[str, Any]]:
        client = self._get_consumption_client(scope)
        try:
            budgets = await asyncio.to_thread(lambda: list(client.budgets.list(scope)))
            budget_list: list[dict[str, Any]] = []
            for budget in budgets:
                time_period = getattr(budget, "time_period", None)
                start_date = getattr(time_period, "start_date", None)
                end_date = getattr(time_period, "end_date", None)
                budget_list.append(
                    {
                        "name": getattr(budget, "name", None),
                        "amount": getattr(budget, "amount", None),
                        "time_grain": getattr(budget, "time_grain", None),
                        "time_period": {
                            "start_date": _to_iso(start_date),
                            "end_date": _to_iso(end_date),
                        },
                        "current_spend": getattr(budget, "current_spend", None),
                        "notifications": self._extract_notifications(
                            getattr(budget, "notifications", None)
                        ),
                    }
                )
            return budget_list
        except AzureError as e:
            raise ExternalServiceException(f"Failed to get budgets: {e}") from e

    async def create_budget(
        self,
        scope: str,
        budget_name: str,
        amount: float,
        time_grain: str = "Monthly",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        notifications: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        client = self._get_consumption_client(scope)
        budget = Budget(
            amount=amount,
            time_grain=time_grain,
            time_period=BudgetTimePeriod(
                start_date=(
                    start_date
                    or datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                ),
                end_date=end_date,
            ),
            notifications=notifications or {},
            category="Cost",
        )
        try:
            result = await asyncio.to_thread(
                client.budgets.create_or_update, scope, budget_name, budget
            )
            return {
                "name": getattr(result, "name", budget_name),
                "amount": getattr(result, "amount", amount),
                "time_grain": getattr(result, "time_grain", time_grain),
                "status": "created",
            }
        except AzureError as e:
            raise ExternalServiceException(f"Failed to create budget: {e}") from e

    async def get_price_sheet(
        self,
        billing_account_name: str,
        billing_profile_name: str | None = None,
        invoice_name: str | None = None,
    ) -> list[dict[str, Any]]:
        client = self._get_cost_client()
        try:
            if billing_profile_name and invoice_name:
                poller = await asyncio.to_thread(
                    client.price_sheet.begin_download,
                    billing_account_name,
                    billing_profile_name,
                    invoice_name,
                )
            elif billing_profile_name:
                poller = await asyncio.to_thread(
                    client.price_sheet.begin_download_by_billing_profile,
                    billing_account_name,
                    billing_profile_name,
                )
            else:
                raise ExternalServiceException(
                    "billing_profile_name is required when requesting price sheets"
                )
            download = await asyncio.to_thread(poller.result)
            return [
                {
                    "download_url": getattr(download, "download_url", None),
                    "valid_till": _to_iso(getattr(download, "valid_till", None)),
                }
            ]
        except AzureError as e:
            raise ExternalServiceException(f"Failed to get price sheet: {e}") from e

    async def create_cost_export(
        self,
        scope: str,
        export_name: str,
        storage_account_id: str,
        container_name: str,
        directory_path: str,
        recurrence: str = "Daily",
        start_date: datetime | None = None,
    ) -> dict[str, Any]:
        client = self._get_cost_client()
        export_def = Export(
            delivery_info=ExportDeliveryInfo(
                destination=ExportDeliveryDestination(
                    resource_id=storage_account_id,
                    container=container_name,
                    root_folder_path=directory_path,
                )
            ),
            definition=ExportDefinition(
                type="Usage",
                timeframe=TimeframeType.MONTH_TO_DATE,
            ),
            schedule=ExportSchedule(
                status="Active",
                recurrence=recurrence,
                recurrence_period=ExportRecurrencePeriod(
                    from_property=start_date or datetime.utcnow(), to=None
                ),
            ),
        )
        try:
            result = await asyncio.to_thread(
                client.exports.create_or_update, scope, export_name, export_def
            )
            status: str | None = None
            recurrence_value: str | None = None
            schedule_any = getattr(result, "schedule", None)
            if schedule_any is not None:
                schedule = cast(ExportSchedule, schedule_any)
                status = getattr(schedule, "status", None)
                recurrence_value = getattr(schedule, "recurrence", None)
            return {
                "name": getattr(result, "name", export_name),
                "status": status,
                "recurrence": recurrence_value,
                "next_run_time": _to_iso(getattr(result, "next_run_time_estimate", None)),
            }
        except AzureError as e:
            raise ExternalServiceException(f"Failed to create cost export: {e}") from e

    def _extract_notifications(self, notifications: dict[str, Any] | None) -> dict[str, Any]:
        if not notifications:
            return {}
        extracted: dict[str, Any] = {}
        for key, notification in notifications.items():
            extracted[key] = {
                "enabled": getattr(notification, "enabled", False),
                "operator": getattr(notification, "operator", None),
                "threshold": getattr(notification, "threshold", None),
                "contact_emails": getattr(notification, "contact_emails", []),
                "contact_roles": getattr(notification, "contact_roles", []),
            }
        return extracted
