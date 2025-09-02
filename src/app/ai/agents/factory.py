from __future__ import annotations

from typing import Any

from app.ai.agents.base import Agent
from app.ai.agents.chain import ChainAgent, ChainLink
from app.ai.agents.coordinator import CoordinatorAgent
from app.ai.agents.orchestrator import OrchestrationAgent
from app.ai.agents.provisioning import ProvisioningAgent
from app.ai.agents.reactive import ReactiveAgent
from app.ai.agents.types import AgentContext
from app.ai.agents.unified_agent import AgentCapability, UnifiedAgent
from app.core.logging import get_logger

logger = get_logger(__name__)


class AgentFactory:
    _registry: dict[str, type[Agent[Any, Any]]] = {
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

    _instances: dict[str, Agent[Any, Any]] = {}

    @classmethod
    def create(
        cls, agent_type: str, context: AgentContext | None = None, **kwargs: Any
    ) -> Agent[Any, Any]:
        if not agent_type or not isinstance(agent_type, str):
            logger.error("create called with invalid agent_type=%r", agent_type)
            raise ValueError("agent_type must be a non-empty string")

        normalized = agent_type.strip().lower()

        if normalized in cls._deprecated_aliases:
            target, caps = cls._deprecated_aliases[normalized]
            logger.warning("agent_type '%s' is deprecated; using '%s' instead", normalized, target)
            unified_agent = UnifiedAgent(context=context)
            for cap in caps:
                unified_agent.add_capability(cap)
            logger.debug(
                "created UnifiedAgent for deprecated alias '%s' with capabilities=%s",
                normalized,
                caps,
            )
            return unified_agent

        agent_class = cls._registry.get(normalized)
        if not agent_class:
            logger.error("unknown agent_type requested: %s", normalized)
            raise ValueError(f"Unknown agent type: {agent_type}")

        if normalized == "provisioning":
            from app.ai.agents.provisioning import ProvisioningAgent, ProvisioningAgentConfig
            
            user_id = kwargs.get("user_id", "system")
            if not isinstance(user_id, str):
                logger.warning("invalid user_id type %s, using 'system'", type(user_id))
                user_id = "system"
            
            config = kwargs.get("config")
            if config is not None and not isinstance(config, dict | ProvisioningAgentConfig):
                logger.warning("invalid config type %s, using None", type(config))
                config = None
            
            provisioning_agent: Agent[Any, Any] = ProvisioningAgent(
                user_id=user_id,
                context=context,
                config=config,
            )
            logger.debug(
                "created ProvisioningAgent with user_id=%s, config_type=%s",
                user_id,
                type(config).__name__ if config is not None else "None",
            )
            return provisioning_agent

        agent = agent_class(context=context)
        logger.debug("created agent_type=%s instance=%s", normalized, agent.__class__.__name__)
        return agent

    @classmethod
    def register(cls, name: str, agent_class: type[Agent[Any, Any]]) -> None:
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
    ) -> Agent[Any, Any]:
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

            async def processor(data: Any, bound_agent: Agent[Any, Any] = agent) -> Any:
                goal = data.get("goal", "") if isinstance(data, dict) else str(data)
                result = await bound_agent.run(goal)
                return result.result if getattr(result, "success", False) else data

            link_name = f"{agent_type.strip().lower()}_link"
            chain.add_link(ChainLink(name=link_name, processor=processor))
            logger.debug("added link '%s' to pipeline", link_name)
        logger.info("created pipeline with %d link(s)", len(chain.links))
        return chain

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Agent[Any, Any]:
        if not isinstance(config, dict):
            logger.error("from_config expects dict, got %r", type(config))
            raise TypeError("config must be a dict")
        
        cfg = dict(config)
        if "type" not in cfg:
            logger.error("from_config missing required key 'type'")
            raise KeyError("config['type'] is required")
        
        agent_type = str(cfg.pop("type"))
        context_cfg = dict(cfg.pop("context", {}))
        
        try:
            context_kwargs: dict[str, Any] = {}
            
            if "user_id" in context_cfg:
                context_kwargs["user_id"] = str(context_cfg["user_id"])
            if "thread_id" in context_cfg:
                thread_id_val = context_cfg["thread_id"]
                context_kwargs["thread_id"] = (
                    str(thread_id_val) if thread_id_val is not None else None
                )
            if "agent_name" in context_cfg:
                agent_name_val = context_cfg["agent_name"]
                context_kwargs["agent_name"] = (
                    str(agent_name_val) if agent_name_val is not None else None
                )
            if "subscription_id" in context_cfg:
                sub_id_val = context_cfg["subscription_id"]
                context_kwargs["subscription_id"] = (
                    str(sub_id_val) if sub_id_val is not None else None
                )
            if "resource_group" in context_cfg:
                rg_val = context_cfg["resource_group"]
                context_kwargs["resource_group"] = str(rg_val) if rg_val is not None else None
            if "environment" in context_cfg:
                env_value = str(context_cfg["environment"])
                if env_value not in ("dev", "tst", "acc", "prod"):
                    logger.warning("invalid environment '%s', using 'dev'", env_value)
                    env_value = "dev"
                context_kwargs["environment"] = env_value
            if "correlation_id" in context_cfg:
                corr_id_val = context_cfg["correlation_id"]
                context_kwargs["correlation_id"] = (
                    str(corr_id_val) if corr_id_val is not None else None
                )
            if "dry_run" in context_cfg:
                context_kwargs["dry_run"] = bool(context_cfg["dry_run"])
            if "timeout_seconds" in context_cfg:
                timeout_val = float(context_cfg["timeout_seconds"])
                if timeout_val <= 0:
                    logger.warning("invalid timeout_seconds %s, using default 300.0", timeout_val)
                    timeout_val = 300.0
                context_kwargs["timeout_seconds"] = timeout_val
            if "max_parallel_tasks" in context_cfg:
                max_tasks = int(context_cfg["max_parallel_tasks"])
                if max_tasks <= 0:
                    logger.warning("invalid max_parallel_tasks %s, using default 5", max_tasks)
                    max_tasks = 5
                context_kwargs["max_parallel_tasks"] = max_tasks
            if "enable_caching" in context_cfg:
                context_kwargs["enable_caching"] = bool(context_cfg["enable_caching"])
            if "cache_ttl_seconds" in context_cfg:
                cache_ttl = int(context_cfg["cache_ttl_seconds"])
                if cache_ttl <= 0:
                    logger.warning("invalid cache_ttl_seconds %s, using default 300", cache_ttl)
                    cache_ttl = 300
                context_kwargs["cache_ttl_seconds"] = cache_ttl
            if "metadata" in context_cfg and isinstance(context_cfg["metadata"], dict):
                context_kwargs["metadata"] = dict(context_cfg["metadata"])
            
            context = AgentContext(**context_kwargs)
            logger.debug(
                "created AgentContext for agent_type='%s' with user_id='%s', env='%s', dry_run=%s",
                agent_type,
                context.user_id,
                context.environment,
                context.dry_run,
            )
            
        except (ValueError, TypeError, KeyError) as e:
            logger.error("failed to create AgentContext from config: %s", e)
            raise ValueError(f"Invalid context configuration: {e}") from e
        
        try:
            agent = cls.create(agent_type, context, **cfg)
            logger.info(
                "successfully created agent type='%s' with context user_id='%s'",
                agent_type,
                context.user_id,
            )
            return agent
        except Exception as e:
            logger.error("failed to create agent type='%s': %s", agent_type, e)
            raise
