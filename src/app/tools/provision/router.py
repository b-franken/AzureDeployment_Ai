from __future__ import annotations

from typing import Literal, cast

backendname = Literal["sdk", "terraform", "bicep"]


def _normalize_backend(value: str | None) -> backendname | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("sdk", "terraform", "bicep"):
        return cast(backendname, v)
    return None


def pick_backend(env: str, requested: str | None, plan_only: bool) -> backendname:
    e = (env or "").strip().lower()
    r = _normalize_backend(requested)

    if r == "sdk":
        return "sdk"

    if r == "bicep":
        if plan_only:
            return "bicep"
        return "sdk"

    if r == "terraform":
        if plan_only:
            return "terraform"
        return "sdk"

    if e == "prod":
        if plan_only:
            return "terraform"
        return "sdk"

    if plan_only:
        return "terraform"

    return "sdk"
