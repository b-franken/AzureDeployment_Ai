from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.v2.auth import require_role
from app.platform.audit.logger import AuditLogger, AuditQuery

router = APIRouter()
alog = AuditLogger()
audit_role_dependency = require_role("audit_viewer")


class logs_response(BaseModel):
    logs: list[dict[str, Any]]
    count: int


@router.get("/audit/logs", response_model=logs_response)
async def get_audit_logs(
    start_date: Annotated[
        datetime | None, Query(description="ISO 8601, inclusive")
    ] = None,
    end_date: Annotated[
        datetime | None, Query(description="ISO 8601, inclusive")
    ] = None,
    user_id: Annotated[str | None, Query(description="Filter by user id")] = None,
    _page: Annotated[int, Query(ge=1, alias="page")] = 1,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> logs_response:
    q = AuditQuery(
        start_time=start_date, end_time=end_date, user_id=user_id, limit=page_size
    )
    items = await alog.query_events(q)
    return logs_response(logs=[e.__dict__ for e in items], count=len(items))
