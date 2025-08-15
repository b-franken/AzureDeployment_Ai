from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.v2.auth import require_role, token_data
from app.tools.finops.analyzer import CostManagementSystem

router = APIRouter()
cms = CostManagementSystem()
cost_viewer_dependency = require_role("cost_viewer")


class cost_analysis_request(BaseModel):
    subscription_id: str
    start_date: datetime
    end_date: datetime
    group_by: list[str] | None = None
    include_forecast: bool = False
    include_recommendations: bool = False


@router.post("/cost/analysis")
async def analyze(
    req: cost_analysis_request,
    td: Annotated[token_data, Depends(cost_viewer_dependency)],
) -> dict[str, Any]:
    analysis = await cms.analyze_costs(
        req.subscription_id,
        req.start_date,
        req.end_date,
        req.group_by,
    )
    if req.include_forecast:
        analysis["forecast"] = (await cms.forecast_costs(req.subscription_id)).__dict__
    if req.include_recommendations:
        recs = await cms.get_optimization_recommendations(req.subscription_id)
        analysis["recommendations"] = [r.__dict__ for r in recs]
    return analysis
