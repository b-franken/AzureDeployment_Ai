from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from app.ai.llm.factory import get_provider_and_model
from app.ai.tools_definitions import _to_openai_tool_schema


async def map_args_with_function_call(
    tool_name: str,
    schema: dict[str, Any] | None,
    user_input: str,
    provider: str | None,
    model: str | None,
) -> dict[str, Any]:
    """
    Use LLM function-calling with a single tool and force the model to call it.
    Validate the returned arguments against the tool's JSON Schema.
    """
    schema = schema or {"type": "object", "properties": {}, "additionalProperties": True}

    Draft202012Validator.check_schema(schema)

    llm, selected_model = await get_provider_and_model(provider, model)

    tool_def = _to_openai_tool_schema(
        name=tool_name,
        description=f"Argument schema for {tool_name}",
        json_schema=schema,
    )

    messages = [{"role": "user", "content": user_input}]

    raw = await llm.chat_raw(  # type: ignore[attr-defined]
        model=selected_model,
        messages=messages,
        tools=[tool_def],
        tool_choice={"type": "function", "function": {"name": tool_name}},
        temperature=0.01,
        max_tokens=128,
    )

    choices = raw.get("choices", [])
    for choice in choices:
        msg = choice.get("message", {}) or {}
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            if (fn.get("name") or "").strip() != tool_name:
                continue
            args_raw = fn.get("arguments") or {}
            if isinstance(args_raw, str):
                try:
                    args_obj = json.loads(args_raw)
                except json.JSONDecodeError as e:
                    raise ValueError(e.msg) from e
            elif isinstance(args_raw, dict):
                args_obj = dict(args_raw)
            else:
                args_obj = {}

            try:
                Draft202012Validator(schema).validate(args_obj)
            except ValidationError as e:
                raise ValueError(f"Tool argument schema validation failed: {e.message}") from e

            return args_obj

    return {}
