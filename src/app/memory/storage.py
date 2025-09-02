from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from opentelemetry import trace

from app.core.config import MAX_MEMORY, MAX_TOTAL_MEMORY
from app.core.data.repository import get_data_layer
from app.core.logging import get_logger
from app.observability.app_insights import app_insights

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)

Role = Literal["user", "assistant", "system", "tool", "reviewer"]


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    REVIEWER = "reviewer"


@dataclass
class Message:
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class AsyncMemoryStore:
    def __init__(
        self,
        max_memory: int = MAX_MEMORY,
        max_total_memory: int = MAX_TOTAL_MEMORY,
    ):
        self.max_memory = int(max_memory)
        self.max_total_memory = int(max_total_memory)
        self.db = get_data_layer()
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return

            logger.info(
                "Initializing memory store",
                max_memory=self.max_memory,
                max_total_memory=self.max_total_memory,
            )

            with tracer.start_as_current_span("memory_store_initialize") as span:
                span.set_attributes(
                    {
                        "memory.max_memory": self.max_memory,
                        "memory.max_total_memory": self.max_total_memory,
                    }
                )

                await self.db.initialize()
                await self.db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id BIGSERIAL PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        metadata JSONB,
                        timestamp TIMESTAMPTZ DEFAULT now(),
                        created_at TIMESTAMPTZ DEFAULT now()
                    );

                    CREATE INDEX IF NOT EXISTS idx_user_timestamp
                        ON messages (user_id, timestamp DESC);

                    CREATE INDEX IF NOT EXISTS idx_user_created
                        ON messages (user_id, created_at DESC);

                    CREATE INDEX IF NOT EXISTS idx_user_thread_created
                        ON messages (
                            user_id,
                            (metadata->>'thread_id'),
                            created_at DESC
                        );

                    CREATE INDEX IF NOT EXISTS idx_user_agent_created
                        ON messages (
                            user_id,
                            (metadata->>'agent'),
                            created_at DESC
                        );

                    CREATE INDEX IF NOT EXISTS idx_messages_metadata_gin
                        ON messages USING GIN (metadata);
                    """
                )

                self._initialized = True
                logger.info("Memory store initialized successfully")

                app_insights.track_custom_event(
                    "memory_store_initialized",
                    {
                        "max_memory": self.max_memory,
                        "max_total_memory": self.max_total_memory,
                    },
                )

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[Any]:
        await self.initialize()
        async with self.db.connection() as conn:
            yield conn

    async def store_message(
        self,
        user_id: str,
        role: MessageRole | str,
        content: str,
        metadata: dict[str, Any] | None = None,
        *,
        thread_id: str | None = None,
        agent: str | None = None,
    ) -> int:
        with tracer.start_as_current_span(
            "memory_store_message",
            attributes={
                "memory.user_id": user_id,
                "memory.role": str(role),
                "memory.content_length": len(content),
                "memory.has_thread": thread_id is not None,
                "memory.has_agent": agent is not None,
            },
        ) as span:
            if isinstance(role, str):
                role = MessageRole(role)
            merged = dict(metadata or {})
            if thread_id is not None:
                merged["thread_id"] = thread_id
            if agent is not None:
                merged["agent"] = agent

            logger.debug(
                "Storing message",
                user_id=user_id,
                role=role.value,
                content_length=len(content),
                thread_id=thread_id,
                agent=agent,
            )

            async with self.get_connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO messages (user_id, role, content, metadata)
                    VALUES ($1, $2, $3, $4)
                    RETURNING id
                    """,
                    user_id,
                    role.value,
                    content,
                    json.dumps(merged) if merged else None,
                )
            message_id = int(row["id"])
            span.set_attribute("memory.message_id", message_id)

            await self.trim_user_memory(user_id)

            logger.info(
                "Message stored successfully",
                message_id=message_id,
                user_id=user_id,
                role=role.value,
                content_length=len(content),
            )

            app_insights.track_custom_event(
                "message_stored",
                {
                    "user_id": user_id,
                    "role": role.value,
                    "content_length": len(content),
                    "has_thread": thread_id is not None,
                    "has_agent": agent is not None,
                },
            )

            return message_id

    async def get_user_memory(
        self,
        user_id: str,
        limit: int | None = None,
        include_metadata: bool = False,
        *,
        thread_id: str | None = None,
        agent: str | None = None,
    ) -> list[dict[str, Any]]:
        lim = int(limit if limit is not None else self.max_memory)
        conditions: list[str] = ["user_id = $1"]
        params: list[Any] = [user_id]
        idx = 2
        if thread_id is not None:
            conditions.append(f"metadata->>'thread_id' = ${idx}")
            params.append(thread_id)
            idx += 1
        if agent is not None:
            conditions.append(f"metadata->>'agent' = ${idx}")
            params.append(agent)
            idx += 1
        where_sql = " AND ".join(conditions)
        query = f"""
            SELECT role, content, metadata, timestamp
            FROM messages
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT ${idx}
        """
        params.append(lim)
        async with self.get_connection() as conn:
            rows = await conn.fetch(query, *params)
        rows = list(rows)[::-1]
        result: list[dict[str, Any]] = []
        for r in rows:
            item: dict[str, Any] = {"role": r["role"], "content": r["content"]}
            if include_metadata:
                item["metadata"] = r["metadata"] or {}
                item["timestamp"] = r["timestamp"]
            result.append(item)
        return result

    async def get_message_count(self, user_id: str) -> int:
        async with self.get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS c FROM messages WHERE user_id = $1", user_id
            )
        return int(row["c"] if row else 0)

    async def search_messages(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        *,
        thread_id: str | None = None,
        agent: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = ["user_id = $1"]
        params: list[Any] = [user_id]
        idx = 2
        if thread_id is not None:
            conditions.append(f"metadata->>'thread_id' = ${idx}")
            params.append(thread_id)
            idx += 1
        if agent is not None:
            conditions.append(f"metadata->>'agent' = ${idx}")
            params.append(agent)
            idx += 1
        conditions.append(f"content ILIKE '%%' || ${idx} || '%%'")
        params.append(query)
        idx += 1
        where_sql = " AND ".join(conditions)
        sql = f"""
            SELECT role, content, timestamp
            FROM messages
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT ${idx}
        """
        params.append(int(limit))
        async with self.get_connection() as conn:
            rows = await conn.fetch(sql, *params)
        return [
            {"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]} for r in rows
        ]

    async def trim_user_memory(
        self,
        user_id: str,
        max_rows: int | None = None,
    ) -> int:
        with tracer.start_as_current_span(
            "memory_trim_user",
            attributes={
                "memory.user_id": user_id,
                "memory.max_rows": max_rows or self.max_total_memory,
            },
        ) as span:
            cap = int(max_rows if max_rows is not None else self.max_total_memory)

            logger.debug("Trimming user memory", user_id=user_id, max_rows=cap)

            async with self.get_connection() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM messages
                    WHERE user_id = $1
                      AND id NOT IN (
                        SELECT id
                        FROM messages
                        WHERE user_id = $1
                        ORDER BY created_at DESC
                        LIMIT $2
                      )
                    """,
                    user_id,
                    cap,
                )
            deleted = int(result.split()[-1]) if result else 0
            span.set_attribute("memory.deleted_messages", deleted)

            if deleted > 0:
                logger.info(
                    "Trimmed user memory",
                    user_id=user_id,
                    deleted_messages=deleted,
                    max_rows=cap,
                )

                app_insights.track_custom_event(
                    "memory_trimmed",
                    {
                        "user_id": user_id,
                        "deleted_messages": deleted,
                        "max_rows": cap,
                    },
                )
            else:
                logger.debug("No messages to trim", user_id=user_id)

            return deleted

    async def forget_user(self, user_id: str) -> int:
        async with self.get_connection() as conn:
            result = await conn.execute("DELETE FROM messages WHERE user_id = $1", user_id)
        return int(result.split()[-1]) if result else 0

    async def get_deployment_patterns(self, user_id: str) -> list[dict[str, Any]]:
        with tracer.start_as_current_span(
            "get_deployment_patterns",
            attributes={"user_id": user_id},
        ) as span:
            logger.debug("Retrieving deployment patterns", user_id=user_id)

            from app.memory.deployment_learning import get_deployment_learning_service

            learning_service = await get_deployment_learning_service()
            patterns = await learning_service.get_deployment_patterns(user_id)

            result = []
            for pattern in patterns:
                result.append(
                    {
                        "pattern_id": pattern.pattern_id,
                        "resource_types": pattern.resource_types,
                        "frequency": pattern.frequency,
                        "success_rate": pattern.success_rate,
                        "average_cost_per_month": pattern.average_cost_per_month,
                        "common_configurations": pattern.common_configurations,
                        "environment_distribution": pattern.environment_distribution,
                        "last_seen": pattern.last_seen.isoformat(),
                    }
                )

            span.set_attribute("patterns_retrieved", len(result))

            logger.info(
                "Deployment patterns retrieved",
                user_id=user_id,
                patterns_count=len(result),
            )

            return result

    async def get_optimization_insights(self, user_id: str) -> list[dict[str, Any]]:
        with tracer.start_as_current_span(
            "get_optimization_insights",
            attributes={"user_id": user_id},
        ) as span:
            logger.debug("Retrieving optimization insights", user_id=user_id)

            from app.memory.deployment_learning import get_deployment_learning_service

            learning_service = await get_deployment_learning_service()
            optimizations = await learning_service.get_optimization_insights(user_id)

            result = []
            for opt in optimizations:
                result.append(
                    {
                        "optimization_id": opt.optimization_id,
                        "resource_type": opt.resource_type,
                        "original_configuration": opt.original_configuration,
                        "optimized_configuration": opt.optimized_configuration,
                        "cost_savings_percentage": opt.cost_savings_percentage,
                        "performance_impact": opt.performance_impact,
                        "adoption_rate": opt.adoption_rate,
                        "environments": opt.environments,
                    }
                )

            span.set_attribute("optimizations_retrieved", len(result))

            logger.info(
                "Optimization insights retrieved",
                user_id=user_id,
                optimizations_count=len(result),
            )

            return result

    async def get_failure_insights(self, user_id: str) -> list[dict[str, Any]]:
        with tracer.start_as_current_span(
            "get_failure_insights",
            attributes={"user_id": user_id},
        ) as span:
            logger.debug("Retrieving failure insights", user_id=user_id)

            from app.memory.deployment_learning import get_deployment_learning_service

            learning_service = await get_deployment_learning_service()
            failures = await learning_service.get_failure_patterns(user_id)

            result = []
            for failure in failures:
                result.append(
                    {
                        "failure_id": failure.failure_id,
                        "error_type": failure.error_type,
                        "resource_context": failure.resource_context,
                        "frequency": failure.frequency,
                        "resolution_success_rate": failure.resolution_success_rate,
                        "common_causes": failure.common_causes,
                        "recommended_solutions": failure.recommended_solutions,
                        "environments": failure.environments,
                    }
                )

            span.set_attribute("failures_retrieved", len(result))

            logger.info(
                "Failure insights retrieved",
                user_id=user_id,
                failures_count=len(result),
            )

            return result

    async def record_deployment_outcome(
        self,
        user_id: str,
        deployment_id: str,
        resource_types: list[str],
        environment: str,
        success: bool,
        configuration: dict[str, Any],
        error_type: str | None = None,
        error_message: str | None = None,
        cost_estimate: float | None = None,
        duration_seconds: int | None = None,
    ) -> None:
        with tracer.start_as_current_span(
            "record_deployment_outcome",
            attributes={
                "user_id": user_id,
                "deployment_id": deployment_id,
                "success": success,
                "environment": environment,
            },
        ) as span:
            logger.info(
                "Recording deployment outcome for learning",
                user_id=user_id,
                deployment_id=deployment_id,
                success=success,
                environment=environment,
                resource_count=len(resource_types),
            )

            from app.memory.deployment_learning import get_deployment_learning_service

            learning_service = await get_deployment_learning_service()
            await learning_service.record_deployment_outcome(
                user_id=user_id,
                deployment_id=deployment_id,
                resource_types=resource_types,
                environment=environment,
                success=success,
                configuration=configuration,
                error_type=error_type,
                error_message=error_message,
                cost_estimate=cost_estimate,
                duration_seconds=duration_seconds,
            )

            span.set_attribute("outcome_recorded", True)

            app_insights.track_custom_event(
                "deployment_learning_recorded",
                {
                    "user_id": user_id,
                    "success": success,
                    "environment": environment,
                    "resource_count": len(resource_types),
                },
            )

    async def get_statistics(self) -> dict[str, Any]:
        async with self.get_connection() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM messages")
            unique_users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM messages")
            role_rows = await conn.fetch("SELECT role, COUNT(*) AS cnt FROM messages GROUP BY role")
            role_distribution = {r["role"]: r["cnt"] for r in role_rows}

            deployment_stats = {}
            try:
                deployment_total = await conn.fetchval("SELECT COUNT(*) FROM deployment_outcomes")
                deployment_success_rate = await conn.fetchval(
                    "SELECT AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) FROM deployment_outcomes"
                )
                deployment_stats = {
                    "total_deployments": int(deployment_total or 0),
                    "success_rate": float(deployment_success_rate or 0.0),
                }
            except Exception:
                deployment_stats = {"total_deployments": 0, "success_rate": 0.0}

        return {
            "total_messages": int(total or 0),
            "unique_users": int(unique_users or 0),
            "role_distribution": role_distribution,
            "deployment_learning": deployment_stats,
            "database_size_bytes": None,
            "pool_size": None,
            "max_memory": self.max_memory,
            "max_total_memory": self.max_total_memory,
        }


_async_store: AsyncMemoryStore | None = None


async def get_async_store() -> AsyncMemoryStore:
    global _async_store
    if _async_store is None:
        _async_store = AsyncMemoryStore(
            max_memory=MAX_MEMORY,
            max_total_memory=MAX_TOTAL_MEMORY,
        )
        await _async_store.initialize()
    return _async_store
