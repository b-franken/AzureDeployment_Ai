from __future__ import annotations

import json
from typing import Any

from app.ai.llm.factory import get_provider_and_model
from app.ai.nlu.unified_parser import DeploymentIntent, UnifiedParseResult, unified_nlu_parser

SYSTEM_PROMPT = (
    "You are a DevOps assistant. Convert free text into an intent for "
    "provisioning. "
    "Use function-calling and produce one function-call that best "
    "matches the input. "
    "Fill in fields: action, resource_type, name, location, resource_group, "
    "environment, sku, dns_prefix, etc. "
    "Only choose a function if the input truly implies it."
)


def _tools() -> list[dict[str, Any]]:
    common_fields = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "location": {"type": "string"},
            "resource_group": {"type": "string"},
            "environment": {"type": "string"},
            "sku": {"type": "string"},
        },
        "additionalProperties": False,
    }

    def tool(
        name: str, extra: dict[str, Any] | None = None, required: list[str] | None = None
    ) -> dict[str, Any]:
        base = json.loads(json.dumps(common_fields))
        if extra:
            base["properties"].update(extra)
        if required:
            base["required"] = required
        return {
            "type": "function",
            "function": {"name": name, "description": name.replace("_", " "), "parameters": base},
        }

    return [
        tool(
            "create_storage",
            extra={"access_tier": {"type": "string", "enum": ["Hot", "Cool"]}},
            required=["name", "resource_group"],
        ),
        tool(
            "create_webapp",
            extra={
                "runtime": {"type": "string"},
                "plan": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "sku": {"type": "string"},
                        "linux": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            },
            required=["name", "resource_group"],
        ),
        tool(
            "create_aks",
            extra={
                "dns_prefix": {"type": "string"},
                "node_count": {"type": "integer", "minimum": 1},
                "node_vm_size": {"type": "string"},
            },
            required=["name", "resource_group"],
        ),
        tool("create_acr", required=["name", "resource_group"]),
        tool("create_keyvault", required=["name", "resource_group"]),
        tool(
            "create_vm",
            extra={
                "image": {"type": "string"},
                "size": {"type": "string"},
                "admin_username": {"type": "string"},
            },
            required=["name", "resource_group"],
        ),
        tool(
            "create_sql",
            extra={
                "admin_login": {"type": "string"},
                "admin_password": {"type": "string"},
            },
            required=["name", "resource_group"],
        ),
        tool(
            "create_vnet",
            extra={
                "address_space": {"type": "string"},
                "subnets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "address_prefix": {"type": "string"},
                        },
                        "required": ["name", "address_prefix"],
                        "additionalProperties": False,
                    },
                },
            },
            required=["name", "resource_group"],
        ),
        tool("create_resource_group", extra={}, required=["name"]),
    ]


def _map_function_to_resource(fn_name: str) -> str:
    m = {
        "create_storage": "storage",
        "create_webapp": "webapp",
        "create_aks": "aks",
        "create_acr": "acr",
        "create_keyvault": "keyvault",
        "create_vm": "vm",
        "create_sql": "sql",
        "create_vnet": "vnet",
        "create_resource_group": "resource_group",
    }
    return m.get(fn_name, "generic")


def _pick_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            j = json.loads(raw)
            return j if isinstance(j, dict) else {}
        except Exception:
            return {}
    if isinstance(raw, dict):
        return dict(raw)
    return {}


async def parse_with_llm(
    text: str, provider: str | None = None, model: str | None = None
) -> UnifiedParseResult:
    llm, selected = await get_provider_and_model(provider, model)
    tools = _tools()
    from typing import cast

    from app.ai.types import Message

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    resp = await llm.chat_raw(
        model=selected,
        messages=cast(list[Message], messages),
        tools=tools,
        tool_choice="auto",
        temperature=0.01,
    )
    choices = resp.get("choices") or []
    if not choices:
        # Fall back to rule-based parsing only (no embeddings) to avoid redundant calls
        base = unified_nlu_parser(use_embeddings=False).parse(text)
        return UnifiedParseResult(
            text=text,
            intent=base.intent,
            confidence=base.confidence * 0.8,  # Reduce confidence for fallback
            resource_type=base.resource_type,
            resource_name=base.resource_name,
            action=base.action,
            parameters=base.parameters,
            context=base.context,
            advanced_context=base.advanced_context,
            embeddings_scores=base.embeddings_scores,
        )
    msg = dict(choices[0].get("message") or {})
    fcall = None
    tcs = msg.get("tool_calls") or []
    for c in tcs:
        if isinstance(c, dict) and (c.get("type") == "function" or "function" in c):
            fcall = dict(c.get("function") or {})
            break
    if not fcall:
        base2 = unified_nlu_parser(use_embeddings=True).parse(text)
        return UnifiedParseResult(
            text=text,
            intent=base2.intent,
            confidence=base2.confidence,
            resource_type=base2.resource_type,
            resource_name=base2.resource_name,
            action=base2.action,
            parameters=base2.parameters,
            context=base2.context,
            advanced_context=base2.advanced_context,
            embeddings_scores=base2.embeddings_scores,
        )
    fn_name = str(fcall.get("name") or "").strip()
    args = _pick_args(fcall.get("arguments"))
    rtype = _map_function_to_resource(fn_name)
    intent = DeploymentIntent.create
    name = str(args.get("name") or "") or None
    parser = unified_nlu_parser(use_embeddings=True)
    base3 = parser.parse(text)
    params = dict(base3.parameters)
    for k, v in args.items():
        params[k] = v
    action = parser._action(intent, rtype)
    return UnifiedParseResult(
        text=text,
        intent=intent,
        confidence=0.85,
        resource_type=rtype,
        resource_name=name,
        action=action,
        parameters=params,
        context=base3.context,
        advanced_context=base3.advanced_context,
        embeddings_scores=base3.embeddings_scores,
    )
