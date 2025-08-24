from __future__ import annotations

from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.api.routes.auth import TokenData, require_role
from app.api.schemas import CostAnalysisRequest
from app.core.logging import get_logger
from app.tools.finops.analyzer import CostManagementSystem, CostOptimizationStrategy

router = APIRouter()
logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)
cost_viewer_dependency = require_role("cost_viewer")
cms = CostManagementSystem()


@router.get("/insights")
async def insights(
    td: Annotated[TokenData, Depends(cost_viewer_dependency)],
    strategy: str = Query("balanced"),
) -> dict[str, Any]:
    started = perf_counter()
    with tracer.start_as_current_span("cost.insights") as span:
        span.set_attribute("user.id", td.user_id)
        span.set_attribute("subscription.id", td.subscription_id or "")
        span.set_attribute("strategy.raw", strategy or "")
        try:
            try:
                enum_strategy = (
                    CostOptimizationStrategy[strategy.upper()]
                    if strategy
                    else CostOptimizationStrategy.BALANCED
                )
            except KeyError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid strategy"
                ) from e
            data = await cms.get_cost_insights(td.subscription_id)
            recs = await cms.get_optimization_recommendations(
                td.subscription_id,
                strategy=enum_strategy,
                min_savings_threshold=0.0,
            )
            anomalies = await cms.check_anomalies(td.subscription_id, sensitivity="medium")
            took = perf_counter() - started
            span.set_attribute("processing.ms", round(took * 1000, 2))
            logger.info(
                "cost_insights_ok",
                user_id=td.user_id,
                subscription_id=td.subscription_id,
                strategy=enum_strategy.name,
                took_ms=round(took * 1000, 2),
            )
            return {
                "period": (
                    data.get("period")
                    if isinstance(data, dict) and "period" in data
                    else {"start": None, "end": None}
                ),
                "current_month_spend": (
                    data.get("current_month_spend") if isinstance(data, dict) else None
                ),
                "last_month_spend": (
                    data.get("last_month_spend") if isinstance(data, dict) else None
                ),
                "month_over_month_change": (
                    data.get("month_over_month_change") if isinstance(data, dict) else None
                ),
                "projected_month_end_spend": (
                    data.get("projected_month_end_spend") if isinstance(data, dict) else None
                ),
                "reserved_instance_coverage": (
                    data.get("reserved_instance_coverage") if isinstance(data, dict) else None
                ),
                "cost_saving_opportunities": (
                    data.get("cost_saving_opportunities", []) if isinstance(data, dict) else []
                ),
                "top_recommendations": [
                    {
                        "resource": r.resource_id,
                        "action": r.recommendation_type,
                        "savings": r.estimated_monthly_savings,
                        "effort": r.implementation_effort,
                    }
                    for r in (recs or [])[:5]
                ],
                "anomalies": (anomalies or [])[:5],
            }
        except HTTPException:
            span.set_status(Status(StatusCode.ERROR))
            raise
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(
                "cost_insights_failed",
                user_id=td.user_id,
                subscription_id=td.subscription_id,
                strategy=strategy,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="insights_failed"
            ) from e


@router.post("/analysis")
async def analyze(
    req: CostAnalysisRequest,
    td: Annotated[TokenData, Depends(cost_viewer_dependency)],
) -> dict[str, Any]:
    started = perf_counter()
    with tracer.start_as_current_span("cost.analysis") as span:
        span.set_attribute("user.id", td.user_id)
        span.set_attribute("subscription.id", req.subscription_id or "")
        span.set_attribute("include.forecast", bool(req.include_forecast))
        span.set_attribute("include.recommendations", bool(req.include_recommendations))
        try:
            analysis = await cms.analyze_costs(
                req.subscription_id,
                req.start_date,
                req.end_date,
                req.group_by,
            )
            if req.include_forecast:
                forecast_obj = await cms.forecast_costs(req.subscription_id)
                analysis["forecast"] = getattr(forecast_obj, "__dict__", forecast_obj)
            if req.include_recommendations:
                recs = await cms.get_optimization_recommendations(req.subscription_id)
                analysis["recommendations"] = [getattr(r, "__dict__", r) for r in (recs or [])]
            took = perf_counter() - started
            span.set_attribute("processing.ms", round(took * 1000, 2))
            logger.info(
                "cost_analysis_ok",
                user_id=td.user_id,
                subscription_id=req.subscription_id,
                group_by=",".join(req.group_by or []),
                include_forecast=bool(req.include_forecast),
                include_recommendations=bool(req.include_recommendations),
                took_ms=round(took * 1000, 2),
            )
            return analysis
        except HTTPException:
            span.set_status(Status(StatusCode.ERROR))
            raise
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(
                "cost_analysis_failed",
                user_id=td.user_id,
                subscription_id=req.subscription_id,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="analysis_failed"
            ) from e
