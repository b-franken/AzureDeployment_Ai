from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel
from app.ai.agents.base import Agent
from app.ai.agents.types import ExecutionPlan, PlanStep
from app.ai.generator import generate_response
from app.ai.nlu import maybe_map_provision
from app.ai.tools_router import ToolExecutionContext
from app.platform.audit.logger import AuditLogger
from app.tools.registry import ensure_tools_loaded, get_tool
from app.runtime.streams import streaming_handler


class ProvisioningAgentConfig(BaseModel):
    provider: str | None = None
    model: str | None = None
    allow_chain: bool = True
    max_steps: int = 6
    token_budget: int = 8000


class ProvisioningAgent(Agent):
    def __init__(self, user_id: str, context: ToolExecutionContext | None = None, config: ProvisioningAgentConfig | None = None) -> None:
        self.user_id = user_id
        self.context = context
        self.config = config or ProvisioningAgentConfig()

    async def plan(self, goal: str) -> ExecutionPlan:
        ensure_tools_loaded()
        direct = maybe_map_provision(goal)
        if isinstance(direct, dict) and direct.get("tool") and isinstance(direct.get("args"), dict):
            return ExecutionPlan(steps=[PlanStep(kind="tool", name=str(direct["tool"]), args=dict(direct["args"]))])
        thought = await generate_response(
            f"Given the goal:\n{goal}\nDecide the single best provisioning tool to call and the arguments as JSON.",
            memory=[],
            provider=self.config.provider,
            model=self.config.model,
        )
        mapped = maybe_map_provision(thought)
        if isinstance(mapped, dict) and mapped.get("tool") and isinstance(mapped.get("args"), dict):
            return ExecutionPlan(steps=[PlanStep(kind="tool", name=str(mapped["tool"]), args=dict(mapped["args"]))])
        return ExecutionPlan(steps=[PlanStep(kind="message", content=thought)])

    async def run(self, plan: ExecutionPlan) -> dict[str, Any]:
        deployment_id = None
        for step in plan.steps:
            if step.kind == "message":
                await streaming_handler.stream_deployment("ad-hoc")
                continue
            tool = get_tool(step.name or "")
            if not tool:
                return {"ok": False, "error": f"tool {step.name} not found"}
            async with streaming_handler.stream_deployment(step.name or "deployment") as stream:
                deployment_id = step.name or "deployment"
                await stream.send(f"Starting: {step.name}")
                try:
                    result = await tool.run(**(step.args or {}))
                    await stream.send("Completed: tool")
                    await stream.close()
                    return result if isinstance(result, dict) else {"ok": True, "output": result}
                except Exception as e:
                    await stream.send(f"Failed: {str(e)}")
                    await stream.close()
                    raise
        return {"ok": True, "result": "noop", "deployment_id": deployment_id}
