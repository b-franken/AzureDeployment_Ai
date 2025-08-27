from __future__ import annotations

from typing import Any

from app.ai.nlu import parse_provision_request

from ..actions.registry import resolve_action


def resolve_action_intelligently(action_input: str, params: dict[str, Any]) -> str:
    r = parse_provision_request(action_input)
    if r.parameters:
        params.update(r.parameters)
    canon, _ = resolve_action(r.action)
    if canon:
        return canon
    canon2, _ = resolve_action(action_input)
    if canon2:
        return canon2
    if r.resource_type and params.get("name"):
        return f"create_{r.resource_type}"
    return "create_rg"
