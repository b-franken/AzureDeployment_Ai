from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal


class StepType(Enum):
    TOOL = "tool"
    MESSAGE = "message"
    DECISION = "decision"
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"
    SEQUENCE = "sequential"  # Alias for SEQUENTIAL
    CONDITIONAL = "conditional"
    AGENT = "agent"


@dataclass
class PlanStep:
    type: StepType
    name: str | None = None
    description: str | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    content: str | None = None
    agent: str | None = None
    dependencies: list[str] = field(default_factory=list)
    conditions: dict[str, Any] | None = None
    timeout_seconds: float = 60.0
    retry_count: int = 0
    max_retries: int = 3
    children: list[PlanStep] | None = field(default_factory=lambda: None)


@dataclass
class ExecutionPlan:
    steps: list[PlanStep]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    estimated_duration_seconds: float | None = None
    resource_requirements: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    step_name: str
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    retries_used: int = 0
    children: list[StepResult] | None = field(default_factory=lambda: None)


@dataclass
class ExecutionResult[TResult]:
    success: bool
    result: TResult | None = None
    error: str | None = None
    execution_time: datetime = field(default_factory=datetime.utcnow)
    duration_ms: float = 0.0
    step_results: list[StepResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    user_id: str = "system"
    thread_id: str | None = None
    agent_name: str | None = None
    subscription_id: str | None = None
    resource_group: str | None = None
    environment: Literal["dev", "tst", "acc", "prod"] = "dev"
    correlation_id: str | None = None
    dry_run: bool = True
    timeout_seconds: float = 300.0
    max_parallel_tasks: int = 5
    enable_caching: bool = True
    cache_ttl_seconds: int = 300
    metadata: dict[str, Any] = field(default_factory=dict)
