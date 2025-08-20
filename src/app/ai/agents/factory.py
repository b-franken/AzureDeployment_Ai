from __future__ import annotations
from typing import Any, Type
from chain import ChainLink
from app.ai.agents.base import Agent, AgentContext
from app.ai.agents.orchestrator import OrchestrationAgent
from app.ai.agents.provisioning import ProvisioningAgent
from app.ai.agents.reactive import ReactiveAgent
from app.ai.agents.coordinator import CoordinatorAgent
from app.ai.agents.chain import ChainAgent
from app.ai.agents.supervisor import SupervisorAgent, SupervisionStrategy
from app.ai.agents.learning import LearningAgent


class AgentFactory:
    _registry: dict[str, Type[Agent]] = {
        "orchestrator": OrchestrationAgent,
        "provisioning": ProvisioningAgent,
        "reactive": ReactiveAgent,
        "coordinator": CoordinatorAgent,
        "chain": ChainAgent,
        "supervisor": SupervisorAgent,
        "learning": LearningAgent
    }

    _instances: dict[str, Agent] = {}

    @classmethod
    def create(
        cls,
        agent_type: str,
        context: AgentContext | None = None,
        **kwargs: Any
    ) -> Agent:
        agent_class = cls._registry.get(agent_type)

        if not agent_class:
            raise ValueError(f"Unknown agent type: {agent_type}")

        if agent_type == "provisioning":
            return agent_class(
                user_id=kwargs.get("user_id", "system"),
                context=context,
                config=kwargs.get("config")
            )

        if agent_type == "supervisor":
            strategy = kwargs.get("strategy", SupervisionStrategy.LEAST_LOADED)
            return agent_class(context=context, strategy=strategy)

        return agent_class(context=context)

    @classmethod
    def register(cls, name: str, agent_class: Type[Agent]) -> None:
        cls._registry[name] = agent_class

    @classmethod
    def get_or_create(
        cls,
        agent_type: str,
        instance_id: str | None = None,
        context: AgentContext | None = None,
        **kwargs: Any
    ) -> Agent:
        key = f"{agent_type}:{instance_id or 'default'}"

        if key not in cls._instances:
            cls._instances[key] = cls.create(agent_type, context, **kwargs)

        return cls._instances[key]

    @classmethod
    def list_available(cls) -> list[str]:
        return list(cls._registry.keys())

    @classmethod
    def clear_instances(cls) -> None:
        cls._instances.clear()

    @classmethod
    def create_pipeline(
        cls,
        agents: list[tuple[str, dict[str, Any]]],
        context: AgentContext | None = None
    ) -> ChainAgent:
        chain = ChainAgent(context=context)

        for agent_type, config in agents:
            agent = cls.create(agent_type, context, **config)

            async def processor(data: Any, bound_agent: Agent = agent) -> Any:
                goal = data.get("goal", "") if isinstance(
                    data, dict) else str(data)
                result = await bound_agent.run(goal)
                return result.result if result.success else data

            chain.add_link(
                ChainLink(
                    name=f"{agent_type}_link",
                    processor=processor
                )
            )

        return chain

    @classmethod
    def create_ensemble(
        cls,
        agent_configs: list[dict[str, Any]],
        strategy: SupervisionStrategy = SupervisionStrategy.LEAST_LOADED,
        context: AgentContext | None = None
    ) -> SupervisorAgent:
        supervisor = SupervisorAgent(context=context, strategy=strategy)

        for config in agent_configs:
            agent_type = config.pop("type")
            skills = config.pop("skills", set())
            priority = config.pop("priority", 0)

            agent = cls.create(agent_type, context, **config)
            supervisor.add_worker(agent, skills=skills, priority=priority)

        return supervisor

    @classmethod
    def create_with_learning(
        cls,
        base_agent_type: str,
        context: AgentContext | None = None,
        **kwargs: Any
    ) -> CoordinatorAgent:
        coordinator = CoordinatorAgent(context=context)

        base_agent = cls.create(base_agent_type, context, **kwargs)
        learning_agent = LearningAgent(context=context)

        coordinator.register_agent("base", base_agent)
        coordinator.register_agent("learning", learning_agent)

        return coordinator

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Agent:
        agent_type = config.pop("type")
        context_config = config.pop("context", {})

        context = AgentContext(
            user_id=context_config.get("user_id", "system"),
            environment=context_config.get("environment", "dev"),
            dry_run=context_config.get("dry_run", True),
            timeout_seconds=context_config.get("timeout_seconds", 300.0),
            metadata=context_config.get("metadata", {})
        )

        return cls.create(agent_type, context, **config)

    @classmethod
    def create_specialized(
        cls,
        specialization: str,
        context: AgentContext | None = None
    ) -> Agent:
        specializations = {
            "infrastructure": {
                "type": "coordinator",
                "agents": [
                    {"type": "provisioning", "skills": {"terraform", "bicep"}},
                    {"type": "reactive", "skills": {"monitoring", "alerting"}}
                ]
            },
            "deployment": {
                "type": "supervisor",
                "strategy": SupervisionStrategy.PRIORITY_BASED,
                "workers": [
                    {"type": "orchestrator", "priority": 1},
                    {"type": "provisioning", "priority": 2}
                ]
            },
            "monitoring": {
                "type": "reactive",
                "event_handlers": ["cost_threshold", "resource_failure", "security_alert"]
            },
            "ml_ops": {
                "type": "learning",
                "exploration_rate": 0.2
            }
        }

        spec = specializations.get(specialization)
        if not spec:
            raise ValueError(f"Unknown specialization: {specialization}")

        if specialization == "infrastructure":
            coordinator = CoordinatorAgent(context=context)
            for agent_config in spec["agents"]:
                agent = cls.create(agent_config["type"], context)
                coordinator.register_agent(agent_config["type"], agent)
            return coordinator

        elif specialization == "deployment":
            supervisor = SupervisorAgent(
                context=context,
                strategy=spec["strategy"]
            )
            for worker_config in spec["workers"]:
                agent = cls.create(worker_config["type"], context)
                supervisor.add_worker(
                    agent, priority=worker_config["priority"])
            return supervisor

        else:
            return cls.create(spec["type"], context)
