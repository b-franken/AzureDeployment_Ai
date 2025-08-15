from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from app.ai.generator import generate_response
from app.ai.llm.factory import get_provider_and_model
from app.ai.llm.openai_provider import OpenAIProvider
from app.ai.nlu import maybe_map_provision
from app.ai.nlu.embeddings_classifier import EmbeddingsClassifierService
from app.ai.tools_definitions import build_openai_tools
from app.platform.audit.logger import (
    AuditEvent,
    AuditEventType,
    AuditLogger,
    AuditSeverity,
)
from app.tools.registry import ensure_tools_loaded, get_tool, list_tools

_TOOLS_PLAN = (
    'You can call a tool by returning only JSON like {"tool":"name","args":{...}}. '
    "When you call a tool, return only the JSON with no prose."
)

_CODEFENCE_JSON_RE = re.compile(
    r"(?:```(?:json)?\s*)?(\{.*?\})(?:\s*```)?\s*", re.DOTALL
)
DIRECT_TOOL_RE = re.compile(
    r"^\s*tool\s*:\s*([a-z0-9-]+)\s*(\{.*\})\s*$", re.IGNORECASE | re.DOTALL
)


@dataclass
class ToolExecutionContext:
    user_id: str
    subscription_id: str | None = None
    resource_group: str | None = None
    environment: Literal["dev", "tst", "acc", "prod"] = "dev"
    correlation_id: str | None = None
    audit_enabled: bool = True
    cost_limit: int | None = None
    approval_threshold: float | None = None
    dry_run: bool = True
    classifier: EmbeddingsClassifierService | None = None
    audit_logger: AuditLogger | None = None


def _extract_json_object(text: str) -> dict[str, object] | None:
    s = text.strip()
    m = _CODEFENCE_JSON_RE.search(s)
    if m:
        s = m.group(1).strip()
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    end_idx = -1
    for i, ch in enumerate(s[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_idx = i + 1
                break
    if end_idx == -1:
        return None
    try:
        obj = json.loads(s[start:end_idx].strip())
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


async def _log_request(user_input: str, context: ToolExecutionContext | None) -> None:
    if not context or not context.audit_enabled or not context.audit_logger:
        return
    event = AuditEvent(
        event_type=AuditEventType.ACCESS_GRANTED,
        severity=AuditSeverity.INFO,
        user_id=context.user_id,
        action="request_received",
        details={"input": user_input[:500]},
        correlation_id=context.correlation_id,
    )
    await context.audit_logger.log_event(event)


async def _log_tool_execution(
    name: str, args: dict[str, object], context: ToolExecutionContext | None
) -> None:
    if not context or not context.audit_enabled or not context.audit_logger:
        return
    event = AuditEvent(
        event_type=AuditEventType.RESOURCE_CREATED,
        severity=AuditSeverity.INFO,
        user_id=context.user_id,
        action="tool_execution",
        resource_type="tool",
        resource_name=name,
        details={"arguments": args},
        correlation_id=context.correlation_id,
    )
    await context.audit_logger.log_event(event)


async def _log_error(error: Exception, context: ToolExecutionContext | None) -> None:
    if not context or not context.audit_enabled or not context.audit_logger:
        return
    event = AuditEvent(
        event_type=AuditEventType.DEPLOYMENT_FAILED,
        severity=AuditSeverity.ERROR,
        user_id=context.user_id,
        action="error",
        result="failed",
        details={"error": str(error)},
        correlation_id=context.correlation_id,
    )
    await context.audit_logger.log_event(event)


def _estimate_tokens(messages: Sequence[dict[str, object]]) -> int:
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += max(1, len(c) // 4)
        elif isinstance(c, dict):
            total += max(1, len(json.dumps(c)) // 4)
    return total


def _within_budget(messages: Sequence[dict[str, object]], limit: int) -> bool:
    return _estimate_tokens(messages) < limit


def _pick_args(raw_args: object) -> dict[str, object]:
    if isinstance(raw_args, str):
        try:
            j = json.loads(raw_args)
            return j if isinstance(j, dict) else {}
        except Exception:
            return {}
    if isinstance(raw_args, dict):
        return dict(raw_args)
    return {}


def _format_tool_body(body: object) -> str:
    if isinstance(body, dict) or isinstance(body, list):
        return json.dumps(body, ensure_ascii=False, indent=2)
    if body is None:
        return ""
    return str(body)


def _maybe_wrap_approval(
    result: dict[str, object], context: ToolExecutionContext | None
) -> dict[str, object]:
    if not context or context.approval_threshold is None:
        return result
    try:
        ce_obj = result.get("cost_estimate")
        monthly: float | None = None
        if isinstance(ce_obj, dict):
            mt_val = ce_obj.get("monthly_total")
            if isinstance(mt_val, int | float):
                monthly = float(mt_val)
            elif isinstance(mt_val, str):
                try:
                    monthly = float(mt_val)
                except ValueError:
                    monthly = None
        if monthly is not None and monthly > context.approval_threshold:
            wrapped: dict[str, object] = dict(result)
            wrapped["status"] = "approval_required"
            return wrapped
    except Exception:
        return result
    return result


async def _run_tool(
    name: str, args: dict[str, object], context: ToolExecutionContext | None = None
) -> dict[str, object]:
    await _log_tool_execution(name, args, context)
    if name == "bert_classifier":
        text = args.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return {"ok": False, "summary": "No text provided", "output": ""}
        svc = context.classifier if context else None
        if not svc:
            return {"ok": False, "summary": "Classifier unavailable", "output": ""}
        scores = svc.predict_proba([text])
        return {
            "ok": True,
            "summary": f"Predicted class {int(scores.argmax(dim=-1).item())}",
            "output": scores.cpu().tolist(),
        }
    tool = get_tool(name)
    if not tool:
        return {"ok": False, "summary": f"tool {name} not found", "output": ""}
    raw = await tool.run(**args)
    result = (
        raw if isinstance(raw, dict) else {"ok": True, "summary": "", "output": raw}
    )
    if isinstance(result, dict):
        result = _maybe_wrap_approval(result, context)
    return result


async def _openai_tools_orchestrator(
    user_input: str,
    memory: Sequence[Mapping[str, str]] | None,
    provider: str | None,
    model: str | None,
    allow_chaining: bool,
    max_chain_steps: int,
    token_budget: int,
    context: ToolExecutionContext | None,
) -> str | None:
    ensure_tools_loaded()
    tools = build_openai_tools()
    if not tools:
        return None
    _, selected_model = get_provider_and_model("openai", model)
    messages: list[dict[str, object]] = [
        {
            "role": "system",
            "content": (
                "You are a DevOps assistant. an expert in infrastructure,"
                " CI/CD, Kubernetes, Terraform, cloud platforms, monitoring, and automation."
                " Provide accurate, concise, production-ready guidance."
            ),
        }
    ]
    if memory:
        messages.extend([{"role": m["role"], "content": m["content"]} for m in memory])
    messages.append({"role": "user", "content": user_input})
    openai = OpenAIProvider()
    if not allow_chaining:
        first = await openai.chat_raw(
            model=selected_model, messages=messages, tools=tools, tool_choice="auto"
        )
        msg = (first.get("choices") or [{}])[0].get("message") or {}
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            content = (msg.get("content") or "").strip()
            return content or None
        call = tool_calls[0]
        if call.get("type") != "function":
            return "Tool call not supported."
        fn = call.get("function") or {}
        tname = (fn.get("name") or "").strip()
        args = _pick_args(fn.get("arguments") or {})
        result = await _run_tool(tname, args, context)
        body = result.get("output") if isinstance(result, dict) else result
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False, indent=2)
        return f"{tname} • {result.get('summary', '')}\n\njson\n{body}\n"
    steps = 0
    while steps < max_chain_steps and _within_budget(messages, token_budget):
        resp = await openai.chat_raw(
            model=selected_model, messages=messages, tools=tools, tool_choice="auto"
        )
        msg = (resp.get("choices") or [{}])[0].get("message") or {}
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            content = (msg.get("content") or "").strip()
            return content or None
        messages.append(
            {
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": tool_calls,
            }
        )
        for call in tool_calls:
            if steps >= max_chain_steps or not _within_budget(messages, token_budget):
                break
            if call.get("type") != "function":
                continue
            fn = call.get("function") or {}
            tname = (fn.get("name") or "").strip()
            args = _pick_args(fn.get("arguments") or {})
            result = await _run_tool(tname, args, context)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": tname,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
            steps += 1
    final = await openai.chat_raw(
        model=selected_model, messages=messages, tools=tools, tool_choice="none"
    )
    content = (final.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return content.strip() or None


async def _run_tool_and_explain(
    name: str,
    args: dict[str, object],
    provider: str | None,
    model: str | None,
    context: ToolExecutionContext | None,
) -> str:
    result = await _run_tool(name, args, context)
    summary = json.dumps(result, ensure_ascii=False)
    return await generate_response(
        f"Tool {name} executed with args {json.dumps(args, ensure_ascii=False)}.\n"
        f"Result JSON:\n{summary}\n\n"
        "Summarize the outcome for a DevOps engineer and list the next best step.",
        memory=[],
        provider=provider,
        model=model,
    )


async def maybe_call_tool(
    user_input: str,
    memory: Sequence[Mapping[str, str]] | None = None,
    provider: str | None = None,
    model: str | None = None,
    enable_tools: bool = False,
    allowlist: list[str] | None = None,
    preferred_tool: str | None = None,
    context: ToolExecutionContext | None = None,
    return_json: bool = False,
) -> str:
    await _log_request(user_input, context)
    if context and context.classifier:
        try:
            _ = context.classifier.predict_proba([user_input])
        except Exception:
            pass
    if not enable_tools:
        try:
            return await generate_response(
                user_input, list(memory or []), model=model, provider=provider
            )
        except Exception as e:
            await _log_error(e, context)
            return "Failed to generate response."
    ensure_tools_loaded()
    try:
        mapped = maybe_map_provision(user_input)
        if (
            mapped
            and isinstance(mapped, dict)
            and mapped.get("tool")
            and isinstance(mapped.get("args"), dict)
        ):
            if return_json:
                res = await _run_tool(
                    str(mapped["tool"]), dict(mapped["args"]), context
                )
                return json.dumps(res, ensure_ascii=False, indent=2)
            return await _run_tool_and_explain(
                str(mapped["tool"]), dict(mapped["args"]), provider, model, context
            )
        tools = list_tools()
        if allowlist:
            allowed = set(allowlist)
            tools = [t for t in tools if t.name in allowed]
        via_openai = await _openai_tools_orchestrator(
            user_input,
            memory,
            provider,
            model,
            allow_chaining=True,
            max_chain_steps=4,
            token_budget=(
                int(context.cost_limit) if context and context.cost_limit else 6000
            ),
            context=context,
        )
        if isinstance(via_openai, str):
            mapped2 = maybe_map_provision(via_openai)
            if (
                mapped2
                and isinstance(mapped2, dict)
                and mapped2.get("tool")
                and isinstance(mapped2.get("args"), dict)
            ):
                if return_json:
                    res = await _run_tool(
                        str(mapped2["tool"]), dict(mapped2["args"]), context
                    )
                    return json.dumps(res, ensure_ascii=False, indent=2)
                return await _run_tool_and_explain(
                    str(mapped2["tool"]),
                    dict(mapped2["args"]),
                    provider,
                    model,
                    context,
                )
            return via_openai
        m = DIRECT_TOOL_RE.match(user_input)
        if m:
            name = m.group(1).strip()
            raw = m.group(2)
            try:
                args_obj = json.loads(raw)
                if not isinstance(args_obj, dict):
                    return "Invalid direct tool args. Provide a JSON object."
                if return_json:
                    res = await _run_tool(name, dict(args_obj), context)
                    return json.dumps(res, ensure_ascii=False, indent=2)
                return await _run_tool_and_explain(
                    name, dict(args_obj), provider, model, context
                )
            except Exception:
                return "Invalid direct tool syntax. Use: tool:tool_name {json-args}"
        if preferred_tool:
            t = get_tool(preferred_tool)
            if not t or (allowlist and preferred_tool not in set(allowlist)):
                return f"Preferred tool {preferred_tool} is not available."
            schema = getattr(
                t,
                "schema",
                {"type": "object", "properties": {}, "additionalProperties": True},
            )
            prompt = (
                "You are a strict argument mapper. Given a tool schema and a user request, "
                "return only a JSON object for the tool's args. No prose."
            )
            args_text = await generate_response(
                (
                    f"{prompt}\n"
                    f"Tool: {preferred_tool}\n"
                    f"Schema:\n{json.dumps(schema)}\n"
                    f"User request:\n{user_input}"
                ),
                memory=[],
                provider=provider,
                model=model,
            )
            obj = _extract_json_object(args_text)
            mapped_args: dict[str, object] = obj if isinstance(obj, dict) else {}
            if return_json:
                res = await _run_tool(preferred_tool, mapped_args, context)
                return json.dumps(res, ensure_ascii=False, indent=2)
            return await _run_tool_and_explain(
                preferred_tool, mapped_args, provider, model, context
            )
        tools_desc = (
            "\n".join(f"- {t.name}: {t.description} schema={t.schema}" for t in tools)
            or "None"
        )
        plan = await generate_response(
            f"{_TOOLS_PLAN}\n\nAvailable tools:\n{tools_desc}\n\nUser: {user_input}",
            list(memory or []),
            model=model,
            provider=provider,
        )
        req = _extract_json_object(plan)
        if not isinstance(req, dict) or "tool" not in req:
            return plan
        name = str(req.get("tool"))
        raw_args = req.get("args")
        args: dict[str, object] = dict(raw_args) if isinstance(raw_args, dict) else {}
        if return_json:
            res = await _run_tool(name, args, context)
            return json.dumps(res, ensure_ascii=False, indent=2)
        return await _run_tool_and_explain(name, args, provider, model, context)
    except Exception as e:
        await _log_error(e, context)
        return "An unexpected error occurred."
