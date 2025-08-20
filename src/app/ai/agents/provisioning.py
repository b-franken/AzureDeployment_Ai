from __future__ import annotations
from typing import Any
from pydantic import BaseModel
from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.types import ExecutionPlan, ExecutionResult, PlanStep, StepType, StepResult
from app.ai.nlu import parse_provision_request
from app.tools.registry import ensure_tools_loaded, get_tool


class ProvisioningAgentConfig(BaseModel):
    provider: str | None = None
    model: str | None = None
    environment: str | None = None


class ProvisioningAgent(Agent[dict[str, Any], dict[str, Any]]):
    def __init__(
        self,
        user_id: str,
        context: AgentContext | None = None,
        config: ProvisioningAgentConfig | dict[str, Any] | None = None
    ):
        super().__init__(context)
        self.user_id = user_id
        if isinstance(config, ProvisioningAgentConfig):
            self.config = config
        elif isinstance(config, dict):
            self.config = ProvisioningAgentConfig(**config)
        else:
            self.config = ProvisioningAgentConfig()
        ensure_tools_loaded()
