from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.routes.auth import TokenData, require_role
from app.api.schemas import LogsResponse
from app.platform.audit.logger import AuditLogger, AuditQuery

router = APIRouter()
alog = AuditLogger()
audit_role_dependency = require_role("audit_viewer")


@router.get("/logs", response_model=LogsResponse)
async def get_audit_logs(
    td: Annotated[TokenData, Depends(audit_role_dependency)],
    start_date: Annotated[datetime | None, Query(description="ISO 8601, inclusive")] = None,
    end_date: Annotated[datetime | None, Query(description="ISO 8601, inclusive")] = None,
    user_id: Annotated[str | None, Query(description="Filter by user id")] = None,
    _page: Annotated[int, Query(ge=1, alias="page")] = 1,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> LogsResponse:
    q = AuditQuery(
        start_time=start_date,
        end_time=end_date,
        user_ids=[user_id] if user_id else None,
        limit=page_size,
    )
    items = await alog.query_events(q)
    return LogsResponse(logs=[e.__dict__ for e in items], count=len(items))
