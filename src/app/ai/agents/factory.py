from __future__ import annotations

from typing import Any

from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.chain import ChainAgent, ChainLink
from app.ai.agents.coordinator import CoordinatorAgent
from app.ai.agents.orchestrator import OrchestrationAgent
from app.ai.agents.provisioning import ProvisioningAgent
from app.ai.agents.reactive import ReactiveAgent
from app.ai.agents.unified_agent import AgentCapability, UnifiedAgent
from app.core.logging import get_logger

logger = get_logger(__name__)


class AgentFactory:
    _registry: dict[str, type[Agent]] = {
        "unified": UnifiedAgent,
        "orchestrator": OrchestrationAgent,
        "provisioning": ProvisioningAgent,
        "reactive": ReactiveAgent,
        "coordinator": CoordinatorAgent,
        "chain": ChainAgent,
    }

    _deprecated_aliases: dict[str, tuple[str, set[AgentCapability]]] = {
        "supervisor": ("unified", set()),
        "learning": ("unified", {AgentCapability.LEARNING}),
    }

    _instances: dict[str, Agent] = {}

    @classmethod
    def create(cls, agent_type: str, context: AgentContext | None = None, **kwargs: Any) -> Agent:
        if not agent_type or not isinstance(agent_type, str):
            logger.error("create called with invalid agent_type=%r", agent_type)
            raise ValueError("agent_type must be a non-empty string")

        normalized = agent_type.strip().lower()

        if normalized in cls._deprecated_aliases:
            target, caps = cls._deprecated_aliases[normalized]
            logger.warning("agent_type '%s' is deprecated; using '%s' instead", normalized, target)
            agent = UnifiedAgent(context=context)
            for cap in caps:
                agent.add_capability(cap)
            logger.debug(
                "created UnifiedAgent for deprecated alias '%s' with capabilities=%s",
                normalized,
                caps,
            )
            return agent

        agent_class = cls._registry.get(normalized)
        if not agent_class:
            logger.error("unknown agent_type requested: %s", normalized)
            raise ValueError(f"Unknown agent type: {agent_type}")

        if normalized == "provisioning":
            agent = agent_class(
                user_id=kwargs.get("user_id", "system"),
                context=context,
                config=kwargs.get("config"),
            )
            logger.debug(
                "created ProvisioningAgent with user_id=%s", kwargs.get("user_id", "system")
            )
            return agent

        agent = agent_class(context=context)
        logger.debug("created agent_type=%s instance=%s", normalized, agent.__class__.__name__)
        return agent

    @classmethod
    def register(cls, name: str, agent_class: type[Agent]) -> None:
        if not name or not isinstance(name, str):
            logger.error("register called with invalid name=%r", name)
            raise ValueError("name must be a non-empty string")
        if not isinstance(agent_class, type):
            logger.error("register called with non-type agent_class=%r", agent_class)
            raise TypeError("agent_class must be a type")
        if not issubclass(agent_class, Agent):
            logger.error(
                "agent_class %s is not a subclass of Agent",
                getattr(agent_class, "__name__", agent_class),
            )
            raise TypeError("agent_class must subclass Agent")
        key = name.strip().lower()
        cls._registry[key] = agent_class
        logger.info("registered agent '%s' -> %s", key, agent_class.__name__)

    @classmethod
    def get_or_create(
        cls,
        agent_type: str,
        instance_id: str | None = None,
        context: AgentContext | None = None,
        **kwargs: Any,
    ) -> Agent:
        key = f"{agent_type.strip().lower()}:{instance_id or 'default'}"
        if key in cls._instances:
            logger.debug("returning cached instance for key=%s", key)
            return cls._instances[key]
        try:
            instance = cls.create(agent_type, context, **kwargs)
        except Exception as exc:
            logger.exception("failed to create instance for key=%s due to %s", key, exc)
            raise
        cls._instances[key] = instance
        logger.debug("cached new instance for key=%s", key)
        return instance

    @classmethod
    def list_available(cls) -> list[str]:
        items = sorted(cls._registry.keys())
        logger.debug("list_available -> %s", items)
        return items

    @classmethod
    def clear_instances(cls) -> None:
        count = len(cls._instances)
        cls._instances.clear()
        logger.info("cleared %d cached agent instance(s)", count)

    @classmethod
    def create_pipeline(
        cls, agents: list[tuple[str, dict[str, Any]]], context: AgentContext | None = None
    ) -> ChainAgent:
        if not isinstance(agents, list):
            logger.error("create_pipeline expects a list, got %r", type(agents))
            raise TypeError("agents must be a list of (agent_type, config) tuples")
        chain = ChainAgent(context=context)
        for agent_type, config in agents:
            agent = cls.create(agent_type, context, **(config or {}))

            async def processor(data: Any, bound_agent: Agent = agent) -> Any:
                goal = data.get("goal", "") if isinstance(data, dict) else str(data)
                result = await bound_agent.run(goal)
                return result.result if getattr(result, "success", False) else data

            link_name = f"{agent_type.strip().lower()}_link"
            chain.add_link(ChainLink(name=link_name, processor=processor))
            logger.debug("added link '%s' to pipeline", link_name)
        logger.info("created pipeline with %d link(s)", len(chain.links))
        return chain

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Agent:
        if not isinstance(config, dict):
            logger.error("from_config expects dict, got %r", type(config))
            raise TypeError("config must be a dict")
        cfg = dict(config)
        if "type" not in cfg:
            logger.error("from_config missing required key 'type'")
            raise KeyError("config['type'] is required")
        agent_type = str(cfg.pop("type"))
        context_cfg = dict(cfg.pop("context", {}))
        context = AgentContext(
            user_id=context_cfg.get("user_id", "system"),
            environment=context_cfg.get("environment", "dev"),
            dry_run=context_cfg.get("dry_run", True),
            timeout_seconds=context_cfg.get("timeout_seconds", 300.0),
            metadata=context_cfg.get("metadata", {}),
        )
        agent = cls.create(agent_type, context, **cfg)
        logger.info("created agent from config type='%s'", agent_type)
        return agent
