from __future__ import annotations

import json
import os
from typing import Any, Literal, cast

from azure.identity import AzureCliCredential, ChainedTokenCredential, ManagedIdentityCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field, field_validator

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


def _subs_from_env() -> tuple[str, ...]:
    raw = os.getenv("AZURE_SUBSCRIPTIONS", "")
    return tuple(s.strip() for s in raw.split(",") if s.strip())


ALLOWED_SUBS = _subs_from_env()
_RG: ResourceGraphClient | None = None


def _get_rg() -> ResourceGraphClient:
    global _RG
    if _RG is not None:
        return _RG
    cred = ChainedTokenCredential(ManagedIdentityCredential(), AzureCliCredential())
    _RG = ResourceGraphClient(cred)
    return _RG


class RGQuery(BaseModel):
    kql: str = Field(
        ..., description="Resource Graph KQL. Must project a stable order when paging."
    )
    top: int = Field(200, ge=1, le=1000)
    skip_token: str | None = None

    @field_validator("kql")
    @classmethod
    def block_dangerous_ops(cls, v: str) -> str:
        lv = v.lower()
        if "| take" in lv or "| sample" in lv:
            raise ValueError("Use 'order by' and optionally 'limit' instead of take/sample.")
        return v


@mcp.resource("azure://overview")
async def azure_overview(_: Context) -> Any:
    rg = _get_rg()
    q = """
    Resources
    | summarize total=count() by type
    | order by total desc
    | limit 25
    """
    req = QueryRequest(query=q, subscriptions=list(ALLOWED_SUBS))
    res = rg.resources(req)
    return res.data


@mcp.tool(
    name="azure_query_resources",
    description="Run a read-only Azure Resource Graph query with paging.",
)
def azure_query_resources(params: RGQuery, _: Context | None = None) -> dict[str, Any]:
    rg = _get_rg()
    req = QueryRequest(
        query=params.kql,
        subscriptions=list(ALLOWED_SUBS),
        options=QueryRequestOptions(top=params.top, skip_token=params.skip_token),
    )
    res = rg.resources(req)
    rows = res.data[: params.top]
    return {
        "data": rows,
        "count": res.count,
        "total_records": res.total_records,
        "skip_token": res.skip_token,
        "result_truncated": res.result_truncated,
    }


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
