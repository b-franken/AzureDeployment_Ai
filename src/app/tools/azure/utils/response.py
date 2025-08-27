from __future__ import annotations

import json
from typing import Any

from app.tools.base import ToolResult


def ok(summary: str, obj: dict | str = "") -> ToolResult:
    return {
        "ok": True,
        "summary": summary,
        "output": (obj if isinstance(obj, str) else json.dumps(obj, default=str, indent=2)),
    }


def err(summary: str, msg: str) -> ToolResult:
    return {"ok": False, "summary": summary, "output": msg}


def dry(summary: str, payload: dict) -> ToolResult:
    return ok(summary, {"dry_run": True, **payload})
