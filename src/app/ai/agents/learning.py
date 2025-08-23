from __future__ import annotations

from app.ai.agents.base import AgentContext
from app.ai.agents.unified_agent import AgentCapability, UnifiedAgent


class LearningAgent(UnifiedAgent):
    def __init__(self, context: AgentContext | None = None):
        super().__init__(context)
        self.add_capability(AgentCapability.LEARNING)
