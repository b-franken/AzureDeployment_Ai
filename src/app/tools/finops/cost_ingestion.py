from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
    ExportDeliveryDestination,
    ExportDeliveryInfo,
    ExportRecurrencePeriod,
    ExportSchedule,
    ForecastDefinition,
    QueryAggregation,
    QueryComparisonExpression,
    QueryDataset,
    QueryDefinition,
    QueryFilter,
    QueryGrouping,
    QueryTimePeriod,
    TimeframeType,
)

from app.core.exceptions import ExternalServiceException, retry_on_error


class CostIngestionService:
    def __init__(self):
        self._credential = DefaultAzureCredential()
        self._client: CostManagementClient | None = None
        self._cache: dict[str, tuple[Any, float]] = {}
        self._cache_ttl = 3600.0

    def _get_client(self) -> CostManagementClient:
        if self._client is None:
            self._client = CostManagementClient(self._credential)
        return self._client

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

        cache_key = f"usage:{scope}:{start_date}:{end_date}:{granularity}:{group_by}:{filter_expression}"
        if cache_key in self._cache:
            cached_data, cached_time = self._cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return cached_data

        client = self._get_client()

        dataset = QueryDataset(
            granularity=granularity,
            aggregation={
                "totalCost": QueryAggregation(name="Cost", function="Sum"),
                "totalCostUSD": QueryAggregation(name="CostUSD", function="Sum"),
            },
        )

        if group_by:
            dataset.grouping = [QueryGrouping(
                type="Dimension", name=dim) for dim in group_by]

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

            usage_data = []
            if result.rows:
                columns = [col.name for col in result.columns]
                for row in result.rows:
                    usage_data.append(dict(zip(columns, row)))

            self._cache[cache_key] = (usage_data, time.time())
            return usage_data
        except AzureError as e:
            raise ExternalServiceException(
                f"Failed to get usage details: {e}") from e

    async def get_resource_costs(
        self,
        scope: str,
        resource_ids: list[str],
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, dict[str, float]]:
        client = self._get_client()
        resource_costs = {}

        for resource_id in resource_ids:
            dataset = QueryDataset(
                granularity="None",
                aggregation={
                    "totalCost": QueryAggregation(name="Cost", function="Sum"),
                    "totalCostUSD": QueryAggregation(name="CostUSD", function="Sum"),
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
                time_period=QueryTimePeriod(
                    from_property=start_date, to=end_date),
                dataset=dataset,
            )

            try:
                result = await asyncio.to_thread(client.query.usage, scope, query_def)

                if result.rows and len(result.rows) > 0:
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
        metric: str = "Cost",
        forecast_days: int = 30,
    ) -> list[dict[str, Any]]:
        client = self._get_client()

        forecast_def = ForecastDefinition(
            type="Usage",
            timeframe=TimeframeType.CUSTOM,
            time_period=QueryTimePeriod(
                from_property=datetime.utcnow(),
                to=datetime.utcnow() + timedelta(days=forecast_days),
            ),
            dataset=QueryDataset(
                granularity=granularity,
                aggregation={
                    "totalCost": QueryAggregation(name=metric, function="Sum"),
                },
            ),
            include_actual_cost=False,
            include_fresh_partial_cost=False,
        )

        try:
            result = await asyncio.to_thread(client.forecast.usage, scope, forecast_def)

            forecast_data = []
            if result.rows:
                columns = [col.name for col in result.columns]
                for row in result.rows:
                    forecast_data.append(dict(zip(columns, row)))

            return forecast_data
        except AzureError as e:
            raise ExternalServiceException(
                f"Failed to get forecast: {e}") from e

    async def get_budgets(self, scope: str) -> list[dict[str, Any]]:
        client = self._get_client()

        try:
            budgets = await asyncio.to_thread(lambda: list(client.budgets.list(scope)))

            budget_list = []
            for budget in budgets:
                budget_list.append(
                    {
                        "name": budget.name,
                        "amount": budget.amount,
                        "time_grain": budget.time_grain,
                        "time_period": {
                            "start_date": budget.time_period.start_date.isoformat()
                            if budget.time_period.start_date
                            else None,
                            "end_date": budget.time_period.end_date.isoformat()
                            if budget.time_period.end_date
                            else None,
                        },
                        "current_spend": getattr(budget, "current_spend", None),
                        "notifications": self._extract_notifications(budget.notifications),
                    }
                )

            return budget_list
        except AzureError as e:
            raise ExternalServiceException(
                f"Failed to get budgets: {e}") from e

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
        from azure.mgmt.costmanagement.models import Budget, BudgetTimePeriod

        client = self._get_client()

        budget = Budget(
            amount=amount,
            time_grain=time_grain,
            time_period=BudgetTimePeriod(
                start_date=start_date or datetime.utcnow().replace(day=1),
                end_date=end_date,
            ),
            notifications=notifications or {},
        )

        try:
            result = await asyncio.to_thread(
                client.budgets.create_or_update, scope, budget_name, budget
            )

            return {
                "name": result.name,
                "amount": result.amount,
                "time_grain": result.time_grain,
                "status": "created",
            }
        except AzureError as e:
            raise ExternalServiceException(
                f"Failed to create budget: {e}") from e

    async def get_price_sheet(
        self,
        billing_account_name: str,
        billing_profile_name: str | None = None,
    ) -> list[dict[str, Any]]:
        client = self._get_client()

        try:
            if billing_profile_name:
                price_sheet = await asyncio.to_thread(
                    client.price_sheet.get_by_billing_profile,
                    billing_account_name,
                    billing_profile_name,
                )
            else:
                price_sheet = await asyncio.to_thread(
                    client.price_sheet.get, billing_account_name
                )

            prices = []
            if price_sheet and price_sheet.properties and price_sheet.properties.price_sheets:
                for price in price_sheet.properties.price_sheets:
                    prices.append(
                        {
                            "meter_id": price.meter_id,
                            "meter_name": price.meter_name,
                            "product_name": price.product_name,
                            "sku_name": price.sku_name,
                            "unit_price": price.unit_price,
                            "currency": price.currency_code,
                            "unit_of_measure": price.unit_of_measure,
                            "included_quantity": price.included_quantity,
                            "effective_date": price.effective_start_date.isoformat()
                            if price.effective_start_date
                            else None,
                        }
                    )

            return prices
        except AzureError as e:
            raise ExternalServiceException(
                f"Failed to get price sheet: {e}") from e

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
        from azure.mgmt.costmanagement.models import Export, ExportDefinition

        client = self._get_client()

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

            return {
                "name": result.name,
                "status": result.schedule.status if result.schedule else None,
                "recurrence": result.schedule.recurrence if result.schedule else None,
                "next_run_time": result.next_run_time_estimate.isoformat()
                if hasattr(result, "next_run_time_estimate") and result.next_run_time_estimate
                else None,
            }
        except AzureError as e:
            raise ExternalServiceException(
                f"Failed to create cost export: {e}") from e

    def _extract_notifications(self, notifications: dict[str, Any] | None) -> dict[str, Any]:
        if not notifications:
            return {}

        extracted = {}
        for key, notification in notifications.items():
            extracted[key] = {
                "enabled": getattr(notification, "enabled", False),
                "operator": getattr(notification, "operator", None),
                "threshold": getattr(notification, "threshold", None),
                "contact_emails": getattr(notification, "contact_emails", []),
                "contact_roles": getattr(notification, "contact_roles", []),
            }
        return extracted

    async def get_reservation_recommendations(
        self,
        scope: str,
        look_back_period: str = "Last30Days",
    ) -> list[dict[str, Any]]:
        client = self._get_client()

        try:
            recommendations = await asyncio.to_thread(
                lambda: list(
                    client.reservation_recommendations.list(
                        scope, filter=f"properties/lookBackPeriod eq '{look_back_period}'"
                    )
                )
            )

            rec_list = []
            for rec in recommendations:
                rec_list.append(
                    {
                        "id": rec.id,
                        "sku": rec.sku,
                        "location": rec.location,
                        "look_back_period": rec.look_back_period,
                        "instance_flexibility_ratio": rec.instance_flexibility_ratio,
                        "normalized_size": rec.normalized_size,
                        "recommended_quantity": rec.recommended_quantity,
                        "cost_with_no_reserved_instances": rec.cost_with_no_reserved_instances,
                        "recommended_quantity_normalized": rec.recommended_quantity_normalized,
                        "net_savings": rec.net_savings,
                        "first_usage_date": rec.first_usage_date.isoformat()
                        if rec.first_usage_date
                        else None,
                    }
                )

            return rec_list
        except AzureError as e:
            raise ExternalServiceException(
                f"Failed to get reservation recommendations: {e}") from e
