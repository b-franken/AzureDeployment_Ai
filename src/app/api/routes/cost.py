from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.routes.auth import TokenData, require_role
from app.api.schemas import CostAnalysisRequest
from app.tools.finops.analyzer import CostManagementSystem

router = APIRouter()
cms = CostManagementSystem()
cost_viewer_dependency = require_role("cost_viewer")


@router.post("/analysis")
async def analyze(
    req: CostAnalysisRequest,
    td: Annotated[TokenData, Depends(cost_viewer_dependency)],
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
