from __future__ import annotations

import copy
import logging

from app.tools.registry import list_tools

logger = logging.getLogger(__name__)


def _to_openai_tool_schema(
    name: str, description: str, json_schema: dict[str, object]
) -> dict[str, object]:
    params: dict[str, object] = copy.deepcopy(json_schema) if isinstance(json_schema, dict) else {}
    if params.get("type") != "object":
        params = {
            "type": "object",
            "properties": {"_input": json_schema},
            "additionalProperties": False,
        }
    if name == "azure_provision":
        try:
            props_in = params.get("properties")
            props: dict[str, object] = dict(props_in) if isinstance(props_in, dict) else {}
            action_in = props.get("action")
            action: dict[str, object] = dict(action_in) if isinstance(action_in, dict) else {}
            action.pop("enum", None)
            props["action"] = action
            params["properties"] = props
        except Exception as exc:
            logger.debug("Failed to sanitize azure_provision schema: %s", exc)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (description or "")[:512],
            "parameters": params,
        },
    }


def build_openai_tools() -> list[dict[str, object]]:
    tools: list[dict[str, object]] = []
    for t in list_tools():
        try:
            tools.append(_to_openai_tool_schema(t.name, t.description, t.schema))
        except Exception as exc:
            logger.debug("Failed to build schema for tool %s: %s", getattr(t, "name", "unknown"), exc)
            continue
    return tools
