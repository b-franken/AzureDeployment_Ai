from __future__ import annotations

import json
import os
from typing import Any, Literal, cast

from mcp.server.fastmcp import FastMCP

from app.tools.registry import ensure_tools_loaded, get_tool, list_tools

mcp = FastMCP(name="DevOps AI Tools")

ensure_tools_loaded()


def _stringify_output(v: Any) -> str:
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, default=str, ensure_ascii=False, indent=2)
    except Exception:
        return str(v)


@mcp.tool(
    name="list_registered_tools", description="List available DevOps AI tools and their schemas."
)
def list_registered_tools() -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "schema": t.schema} for t in list_tools()
    ]


@mcp.tool(name="run_tool", description="Execute a registered tool by name with JSON arguments.")
async def run_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = get_tool(name)
    if tool is None:
        return {"ok": False, "summary": "tool not found", "output": name}
    result = await tool.run(**args)
    out = dict(result)
    out["output"] = _stringify_output(out.get("output", ""))
    return out


@mcp.tool(
    name="provision_orchestrator",
    description="Provision Azure products via the orchestrator backend.",
)
async def provision_orchestrator(
    product: str,
    parameters: dict[str, Any],
    backend: str = "auto",
    env: str = "dev",
    plan_only: bool = True,
) -> dict[str, Any]:
    tool = get_tool("provision_orchestrator")
    if tool is None:
        return {"ok": False, "summary": "tool not found", "output": "provision_orchestrator"}
    result = await tool.run(
        product=product, parameters=parameters, backend=backend, env=env, plan_only=plan_only
    )
    out = dict(result)
    out["output"] = _stringify_output(out.get("output", ""))
    return out


@mcp.tool(
    name="azure_provision",
    description="Provision Azure resources using natural language or structured parameters.",
)
async def azure_provision(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    tool = get_tool("azure_provision")
    if tool is None:
        return {"ok": False, "summary": "tool not found", "output": "azure_provision"}
    payload = dict(params or {})
    result = await tool.run(action=action, **payload)
    out = dict(result)
    out["output"] = _stringify_output(out.get("output", ""))
    return out


@mcp.tool(name="ping", description="Health check.")
def ping() -> str:
    return "pong"


if __name__ == "__main__":
    raw = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if raw == "http":
        raw = "streamable-http"
    if raw not in {"stdio", "sse", "streamable-http"}:
        raw = "stdio"
    transport: Literal["stdio", "sse", "streamable-http"] = cast(
        Literal["stdio", "sse", "streamable-http"], raw
    )
    mcp.run(transport=transport)
