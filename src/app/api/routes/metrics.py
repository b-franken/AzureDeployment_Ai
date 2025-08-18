from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.routes.auth import TokenData, require_role
from app.platform.audit.logger import AuditLogger

router = APIRouter()
alog = AuditLogger()
metrics_role_dependency = require_role("metrics_viewer")


@router.get("")
async def metrics(td: Annotated[TokenData, Depends(metrics_role_dependency)]) -> dict:
    end = datetime.utcnow()
    start = end - timedelta(days=30)
    stats = await alog.get_statistics(start, end)
    return {"audit": stats}
