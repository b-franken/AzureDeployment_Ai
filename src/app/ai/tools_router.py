from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NotRequired, Protocol, TypedDict, runtime_checkable

from app.ai.arg_mapper import map_args_with_function_call
from app.ai.generator import generate_response
from app.ai.llm.factory import get_provider_and_model
from app.ai.nlu import maybe_map_provision, maybe_map_provision_async
from app.ai.nlu.embeddings_classifier import EmbeddingsClassifierService
from app.ai.tools_definitions import build_openai_tools
from app.common.envs import Env
from app.platform.audit.logger import (
    AuditEvent,
    AuditEventType,
    AuditLogger,
    AuditSeverity,
)
from app.tools.registry import ensure_tools_loaded, get_tool, list_tools

logger = logging.getLogger(__name__)

_TOOLS_PLAN = (
    'You can call a tool by returning only JSON like {"tool":"name","args":{...}}. '
    "When you call a tool, return only the JSON with no prose."
)

_CODEFENCE_JSON_RE = re.compile(r"(?:```(?:json)?\s*)?(\{.*?\})(?:\s*```)?\s*", re.DOTALL)
DIRECT_TOOL_RE = re.compile(
    r"^\s*tool\s*:\s*([a-z0-9-]+)\s*(\{.*\})\s*$", re.IGNORECASE | re.DOTALL
)


class ToolFunction(TypedDict, total=False):
    name: str
    arguments: object


class ToolCall(TypedDict, total=False):
    id: NotRequired[str]
    type: NotRequired[str]
    function: ToolFunction


class Message(TypedDict, total=False):
    content: str
    tool_calls: list[ToolCall]


class Choice(TypedDict):
    message: Message


class ChatResponse(TypedDict, total=False):
    choices: list[Choice]


@dataclass
class ToolExecutionContext:
    user_id: str
    subscription_id: str | None = None
    resource_group: str | None = None
    environment: Env = "dev"
    correlation_id: str | None = None
    audit_enabled: bool = True
    cost_limit: int | None = None
    approval_threshold: float | None = None
    dry_run: bool = True
    classifier: EmbeddingsClassifierService | None = None
    audit_logger: AuditLogger | None = None
    # Execution tracking
    tool_execution_count: int = 0
    max_tool_executions: int = 10
    executed_tools: set[str] = None
    last_tool_output: str | None = None

    def __post_init__(self):
        if self.executed_tools is None:
            self.executed_tools = set()


def _extract_json_object(text: str) -> dict[str, object] | None:
    s = text.strip()
    m = _CODEFENCE_JSON_RE.search(s)
    if m:
        extracted = m.group(1).strip()
        try:
            obj = json.loads(extracted)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError as exc:
            logger.debug("Failed to parse JSON object: %s", exc)
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
        raise ValueError("Failed to parse JSON object: no closing '}' found")
    try:
        obj = json.loads(s[start:end_idx].strip())
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError as exc:
        logger.debug("Failed to parse JSON object: %s", exc)
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
    if context:
        context.tool_execution_count += 1
        tool_signature = f"{name}:{hash(str(sorted(args.items())))}"
        if context.tool_execution_count > context.max_tool_executions:
            logger.error(
                "Tool execution limit exceeded (%d). Stopping to prevent infinite loop.",
                context.max_tool_executions,
            )
            return {
                "ok": False,
                "summary": "Execution limit exceeded",
                "output": (
                    "Maximum tool execution limit reached. "
                    "Please try again with a different approach."
                ),
            }
        # Allow Azure provisioning tools to be re-executed as they may be intentionally repeated
        is_provisioning_tool = name in ["azure_provision"]
        if tool_signature in context.executed_tools and not is_provisioning_tool:
            logger.warning(
                (
                    "Duplicate tool execution detected: %s with identical args. "
                    "Skipping to prevent loop."
                ),
                name,
            )
            return {
                "ok": False,
                "summary": "Duplicate execution prevented",
                "output": (
                    f"Tool {name} was already executed with these parameters to prevent loops."
                ),
            }
        if is_provisioning_tool and tool_signature in context.executed_tools:
            logger.info(
                "Re-executing provisioning tool %s - this is allowed for deployment operations.",
                name,
            )

            context.executed_tools.add(tool_signature)

    execution_num = context.tool_execution_count if context else "unknown"
    logger.info("Executing tool: %s with args: %s (execution #%s)", name, args, execution_num)
    await _log_tool_execution(name, args, context)

    merged_args = dict(args or {})
    if context:
        logger.info(
            "Merging context into tool args. context.subscription_id=%s args.subscription_id=%s",
            getattr(context, "subscription_id", None),
            (args or {}).get("subscription_id"),
        )
        if "dry_run" not in merged_args:
            merged_args["dry_run"] = bool(getattr(context, "dry_run", True))
        if "subscription_id" not in merged_args and getattr(context, "subscription_id", None):
            merged_args["subscription_id"] = context.subscription_id
            logger.info("Added subscription_id from context: %s", context.subscription_id)
        elif "subscription_id" in merged_args:
            logger.info("subscription_id already in args: %s", merged_args["subscription_id"])
        else:
            logger.warning("Context has no subscription_id to merge")
        if "resource_group" not in merged_args and getattr(context, "resource_group", None):
            merged_args["resource_group"] = context.resource_group
        if "environment" not in merged_args and getattr(context, "environment", None):
            merged_args["environment"] = context.environment
        if "correlation_id" not in merged_args and getattr(context, "correlation_id", None):
            merged_args["correlation_id"] = context.correlation_id
        if "confirmed" not in merged_args and merged_args.get("dry_run") is False:
            merged_args["confirmed"] = True

    tool = get_tool(name)
    if not tool:
        return {"ok": False, "summary": f"tool {name} not found", "output": ""}

    logger.info(f"About to execute tool {name} with merged_args: {merged_args}")
    try:
        raw = await tool.run(**merged_args)
        logger.info(f"Tool {name} execution completed successfully, result: {raw}")
    except Exception as e:
        logger.error(f"Tool {name} execution failed with exception: {e!s}", exc_info=True)
        raise
    result = raw if isinstance(raw, dict) else {"ok": True, "summary": "", "output": raw}
    if isinstance(result, dict):
        result = _maybe_wrap_approval(result, context)
    return result


@runtime_checkable
class SupportsChatRaw(Protocol):
    async def chat_raw(
        self,
        model: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | None = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse: ...


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
    llm, selected_model = await get_provider_and_model(provider, model)
    logger.info(f"OpenAI orchestrator using provider={provider} -> selected_model={selected_model}")
    if not isinstance(llm, SupportsChatRaw):
        logger.warning(
            f"Provider {provider} does not support chat_raw, skipping OpenAI orchestrator"
        )
        return None
    messages: list[dict[str, object]] = [
        {
            "role": "system",
            "content": (
                "You are a DevOps assistant, an expert in infrastructure, "
                "CI/CD, Kubernetes, Terraform, cloud platforms, monitoring, and automation. "
                "Provide accurate, concise, production-ready guidance.\n\n"
                "CRITICAL: You have access to powerful tools for Azure resource provisioning. "
                "When users request Azure resource deployments, infrastructure changes, "
                "or cloud operations, "
                "you MUST use the available tools rather than just providing text explanations.\n\n"
                "Available tools:\n"
                "- azure_provision: For creating, modifying, or managing Azure resources "
                "using AVM modules\n"
                "- azure_costs: For cost analysis and optimization recommendations\n"
                "- azure_quota_check: For checking subscription limits and quotas\n\n"
                "IMPORTANT: When a tool execution succeeds "
                "(status='created', 'deployed', or 'exists'), "
                "the task is COMPLETE. Do NOT call the same tool again. "
                "If a resource already exists, that means the request was fulfilled successfully."
            ),
        }
    ]
    if memory:
        messages.extend([{"role": m["role"], "content": m["content"]} for m in memory])
    messages.append({"role": "user", "content": user_input})

    # Track rich formatted responses from tools
    last_rich_response: str | None = None

    if not allow_chaining:
        try:
            first = await llm.chat_raw(
                model=selected_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.01,
            )
        except Exception as e:
            logger.error(f"OpenAI orchestrator single call failed: {e}")
            return f"Failed to process request: {e!s}"
        choices = first.get("choices", [])
        if not choices:
            return None
        msg = choices[0]["message"]
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

        if (
            isinstance(result, dict)
            and isinstance(result.get("output"), str)
            and (
                "## Bicep Infrastructure Code" in result.get("output", "")
                or "## Terraform Infrastructure Code" in result.get("output", "")
            )
        ):
            output = result.get("output")

            if context:
                context.last_tool_output = output
            logger.info(
                f"Found infrastructure code in {tname} output (single call), returning directly"
            )
            return output

        body = result.get("output") if isinstance(result, dict) else result
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False, indent=2)
        return f"{tname} • {result.get('summary', '')}\n\njson\n{body}\n"
    steps = 0
    while steps < max_chain_steps and _within_budget(messages, token_budget):
        try:
            resp = await llm.chat_raw(
                model=selected_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.01,
            )
        except Exception as e:
            logger.error(f"OpenAI orchestrator chain step {steps} failed: {e}")
            return f"Tool execution failed at step {steps}: {e!s}"
        choices2 = resp.get("choices", [])
        if not choices2:
            return None
        msg = choices2[0]["message"]
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            content = (msg.get("content") or "").strip()
            logger.info(
                f"OpenAI orchestrator finished - no more tool calls requested (step {steps})"
            )
            # If we have rich formatted content from tools, return that instead of generic response
            if last_rich_response:
                logger.info(
                    "Returning rich infrastructure response instead of generic OpenAI response"
                )
                return last_rich_response
            return content or None
        messages.append(
            {"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls}
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

            if isinstance(result, dict) and isinstance(result.get("output"), str):
                output = result.get("output")
                if (
                    "## Bicep Infrastructure Code" in output
                    or "## Terraform Infrastructure Code" in output
                ):
                    last_rich_response = output

                    if context:
                        context.last_tool_output = output
                    logger.info(f"Captured rich infrastructure response from {tname}")

            # Professional completion detection logic - 2025 standards
            result_summary = result.get("summary", "").lower() if isinstance(result, dict) else ""
            result_output = result.get("output", "") if isinstance(result, dict) else ""
            result_ok = result.get("ok") if isinstance(result, dict) else False

            # Debug logging for detection analysis
            logger.info(
                f"COMPLETION DETECTION DEBUG: tool={tname}, result_type={type(result)}, "
                f"ok={result_ok}, "
                f"summary='{result.get('summary', '') if isinstance(result, dict) else 'N/A'}', "
                f"output_length={len(result_output)}, "
                f"has_bicep_code={'## Bicep Infrastructure Code' in result_output}, "
                f"has_terraform_code={'## Terraform Infrastructure Code' in result_output}"
            )

            is_successful_completion = (
                isinstance(result, dict)
                and result_ok is True
                and (
                    # Check summary for completion keywords
                    any(
                        keyword in result_summary
                        for keyword in ["success", "deployed", "created", "completed", "executed"]
                    )
                    or
                    # Definitive completion: Infrastructure code generated
                    (
                        "## Bicep Infrastructure Code" in result_output
                        or "## Terraform Infrastructure Code" in result_output
                    )
                    or
                    # For Azure operations: Any successful status with "ok": True
                    (tname == "azure_provision" and result_ok is True)
                )
            )

            # Log completion detection for debugging
            if is_successful_completion:
                logger.info(
                    f"SUCCESS DETECTED: {tname} - Breaking tool chain after execution #{steps}"
                )
            else:
                logger.info(
                    f"SUCCESS NOT DETECTED: {tname} - Continuing tool chain (execution #{steps})"
                )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": tname,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
            steps += 1

            # Professional chain breaking logic - 2025 standards
            if is_successful_completion and tname in [
                "azure_provision",
                "terraform_apply",
                "kubectl_apply",
            ]:
                logger.info(
                    f"BREAKING TOOL CHAIN: {tname} completed successfully (execution #{steps}), "
                    f"preventing further repetitions"
                )

                # Always return rich response if available for infrastructure tools
                if last_rich_response:
                    logger.info(
                        "Returning rich infrastructure response, chain terminated successfully"
                    )
                    return last_rich_response

                # If no rich response, construct one from the successful result
                logger.info(
                    "No rich response available, constructing response from successful result"
                )
                output = result.get("output", str(result))
                return output if isinstance(output, str) else json.dumps(result, indent=2)

            (
                # Additional safety check: if we've executed the same tool multiple times
                # successfully, break the chain
            )
            if (
                tname == "azure_provision"
                and steps >= 2
                and isinstance(result, dict)
                and result.get("ok") is True
            ):
                logger.info(
                    f"SAFETY BREAK: azure_provision executed {steps} times successfully, "
                    f"terminating to prevent loops"
                )

                if last_rich_response:
                    return last_rich_response

                output = result.get("output", str(result))
                return output if isinstance(output, str) else json.dumps(result, indent=2)
    try:
        final = await llm.chat_raw(
            model=selected_model,
            messages=messages,
            tools=tools,
            tool_choice="none",
            temperature=0.01,
        )
    except Exception as e:
        logger.error(f"OpenAI orchestrator final call failed: {e}")
        return f"Failed to generate final response: {e!s}"
    choicesf = final.get("choices", [])
    if not choicesf:
        return None
    msgf = choicesf[0]["message"]
    content = (msgf.get("content") or "").strip()

    if last_rich_response:
        logger.info("Returning rich infrastructure response instead of generic OpenAI response")
        return last_rich_response

    logger.info(
        f"No rich content captured, returning OpenAI response: {content[:100]}"
        f"{'...' if content and len(content) > 100 else ''}"
    )
    return content or None


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
    from app.core.config import settings

    logger.info(
        f"maybe_call_tool: user_input='{user_input[:100]}...' provider={provider} "
        f"model={model} enable_tools={enable_tools}"
    )
    await _log_request(user_input, context)

    if context and context.classifier and settings.environment != "development":
        try:
            _ = context.classifier.predict_proba([user_input])
        except Exception as exc:
            logger.debug("Classifier prediction failed: %s", exc)
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
        if not mapped:
            mapped = await maybe_map_provision_async(user_input)
        if (
            mapped
            and isinstance(mapped, dict)
            and mapped.get("tool")
            and isinstance(mapped.get("args"), dict)
        ):
            if return_json:
                res = await _run_tool(str(mapped["tool"]), dict(mapped["args"]), context)
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
            token_budget=(int(context.cost_limit) if context and context.cost_limit else 6000),
            context=context,
        )

        if isinstance(via_openai, str) and via_openai.strip():
            logger.info("OpenAI orchestrator completed successfully, returning result directly")
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
                return await _run_tool_and_explain(name, dict(args_obj), provider, model, context)
            except Exception:
                return "Invalid direct tool syntax. Use: tool:tool_name {json-args}"
        if preferred_tool:
            t = get_tool(preferred_tool)
            if not t or (allowlist and preferred_tool not in set(allowlist)):
                return f"Preferred tool {preferred_tool} is not available."
            schema = getattr(
                t, "schema", {"type": "object", "properties": {}, "additionalProperties": True}
            )
            try:
                mapped_args = await map_args_with_function_call(
                    tool_name=preferred_tool,
                    schema=schema,
                    user_input=user_input,
                    provider=provider,
                    model=model,
                )
            except ValueError as e:
                return f"Invalid tool arguments: {e}"
            if return_json:
                res = await _run_tool(preferred_tool, mapped_args, context)
                return json.dumps(res, ensure_ascii=False, indent=2)
            return await _run_tool_and_explain(
                preferred_tool, mapped_args, provider, model, context
            )
        tools_desc = (
            "\n".join(f"- {t.name}: {t.description} schema={t.schema}" for t in tools) or "None"
        )
        plan = await generate_response(
            f"{_TOOLS_PLAN}\n\nAvailable tools:\n{tools_desc}\n\nUser: {user_input}",
            list(memory or []),
            model=model,
            provider=provider,
        )
        try:
            req = _extract_json_object(plan)
        except ValueError as e:
            await _log_error(e, context)
            return f"Failed to parse tool request: {e}"
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
