from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from opentelemetry import trace

from app.core.logging import get_logger
from app.memory.storage import get_async_store
from app.observability.app_insights import app_insights

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class DeploymentPattern:
    pattern_id: str
    resource_types: list[str]
    frequency: int
    success_rate: float
    average_cost_per_month: float | None = None
    common_configurations: dict[str, Any] = field(default_factory=dict)
    environment_distribution: dict[str, int] = field(default_factory=dict)
    last_seen: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FailurePattern:
    failure_id: str
    error_type: str
    resource_context: dict[str, Any]
    frequency: int
    resolution_success_rate: float
    common_causes: list[str] = field(default_factory=list)
    recommended_solutions: list[str] = field(default_factory=list)
    environments: list[str] = field(default_factory=list)


@dataclass
class CostOptimization:
    optimization_id: str
    resource_type: str
    original_configuration: dict[str, Any]
    optimized_configuration: dict[str, Any]
    cost_savings_percentage: float
    performance_impact: str
    adoption_rate: float
    environments: list[str] = field(default_factory=list)


@dataclass
class DeploymentInsights:
    successful_patterns: list[DeploymentPattern]
    failure_patterns: list[FailurePattern]
    cost_optimizations: list[CostOptimization]
    user_preferences: dict[str, Any] = field(default_factory=dict)
    recommendation_confidence: float = 0.0


class DeploymentLearningService:
    def __init__(self) -> None:
        self._pattern_cache: dict[str, list[DeploymentPattern]] = {}
        self._cache_ttl = 300

    async def initialize(self) -> None:
        store = await get_async_store()
        await store.initialize()
        
        async with store.get_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS deployment_outcomes (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    deployment_id TEXT NOT NULL,
                    resource_types TEXT[] NOT NULL,
                    environment TEXT NOT NULL,
                    success BOOLEAN NOT NULL,
                    error_type TEXT,
                    error_message TEXT,
                    configuration JSONB,
                    cost_estimate DECIMAL(10,2),
                    duration_seconds INTEGER,
                    created_at TIMESTAMPTZ DEFAULT now()
                );

                CREATE INDEX IF NOT EXISTS idx_deployment_outcomes_user_success
                    ON deployment_outcomes (user_id, success, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_deployment_outcomes_resources
                    ON deployment_outcomes USING GIN (resource_types);

                CREATE INDEX IF NOT EXISTS idx_deployment_outcomes_environment
                    ON deployment_outcomes (environment, success);

                CREATE TABLE IF NOT EXISTS cost_optimizations (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    original_config JSONB NOT NULL,
                    optimized_config JSONB NOT NULL,
                    cost_savings_percentage DECIMAL(5,2) NOT NULL,
                    performance_impact TEXT,
                    applied BOOLEAN DEFAULT FALSE,
                    environment TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now()
                );

                CREATE INDEX IF NOT EXISTS idx_cost_optimizations_user_applied
                    ON cost_optimizations (user_id, applied, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_cost_optimizations_resource
                    ON cost_optimizations (resource_type, cost_savings_percentage DESC);
            """)

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
                "resource_count": len(resource_types),
                "environment": environment,
                "success": success,
            },
        ) as span:
            logger.info(
                "Recording deployment outcome",
                user_id=user_id,
                deployment_id=deployment_id,
                resource_types=resource_types,
                environment=environment,
                success=success,
                error_type=error_type,
            )

            store = await get_async_store()
            async with store.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO deployment_outcomes 
                    (user_id, deployment_id, resource_types, environment, success, 
                     error_type, error_message, configuration, cost_estimate, duration_seconds)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    user_id,
                    deployment_id,
                    resource_types,
                    environment,
                    success,
                    error_type,
                    error_message,
                    json.dumps(configuration),
                    cost_estimate,
                    duration_seconds,
                )

            span.set_attributes({
                "outcome_recorded": True,
                "has_error": error_type is not None,
                "has_cost": cost_estimate is not None,
            })

            app_insights.track_custom_event(
                "deployment_outcome_recorded",
                {
                    "user_id": user_id,
                    "resource_count": len(resource_types),
                    "environment": environment,
                    "success": success,
                    "has_error": error_type is not None,
                },
            )

            self._invalidate_pattern_cache(user_id)

    async def record_cost_optimization(
        self,
        user_id: str,
        resource_type: str,
        original_config: dict[str, Any],
        optimized_config: dict[str, Any],
        cost_savings_percentage: float,
        performance_impact: str,
        environment: str,
        applied: bool = False,
    ) -> None:
        with tracer.start_as_current_span(
            "record_cost_optimization",
            attributes={
                "user_id": user_id,
                "resource_type": resource_type,
                "cost_savings_percentage": cost_savings_percentage,
                "environment": environment,
                "applied": applied,
            },
        ):
            logger.info(
                "Recording cost optimization",
                user_id=user_id,
                resource_type=resource_type,
                cost_savings_percentage=cost_savings_percentage,
                performance_impact=performance_impact,
                environment=environment,
                applied=applied,
            )

            store = await get_async_store()
            async with store.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO cost_optimizations 
                    (user_id, resource_type, original_config, optimized_config,
                     cost_savings_percentage, performance_impact, environment, applied)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    user_id,
                    resource_type,
                    json.dumps(original_config),
                    json.dumps(optimized_config),
                    cost_savings_percentage,
                    performance_impact,
                    environment,
                    applied,
                )

            app_insights.track_custom_event(
                "cost_optimization_recorded",
                {
                    "user_id": user_id,
                    "resource_type": resource_type,
                    "cost_savings_percentage": cost_savings_percentage,
                    "applied": applied,
                },
            )

    async def get_deployment_patterns(self, user_id: str) -> list[DeploymentPattern]:
        if user_id in self._pattern_cache:
            return self._pattern_cache[user_id]

        with tracer.start_as_current_span(
            "get_deployment_patterns",
            attributes={"user_id": user_id},
        ) as span:
            logger.debug("Analyzing deployment patterns", user_id=user_id)

            store = await get_async_store()
            async with store.get_connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT 
                        resource_types,
                        environment,
                        COUNT(*) as frequency,
                        AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) as success_rate,
                        AVG(cost_estimate) as avg_cost,
                        MAX(created_at) as last_seen,
                        string_agg(DISTINCT configuration::text, '|||') as configs
                    FROM deployment_outcomes 
                    WHERE user_id = $1 
                      AND created_at > $2
                    GROUP BY resource_types, environment
                    HAVING COUNT(*) >= 2
                    ORDER BY frequency DESC, success_rate DESC
                    LIMIT 20
                    """,
                    user_id,
                    datetime.utcnow() - timedelta(days=90),
                )

            patterns: list[DeploymentPattern] = []
            for row in rows:
                resource_types = row["resource_types"]
                pattern_id = f"{user_id}:{hash(tuple(sorted(resource_types)))}"
                
                common_configs = {}
                if row["configs"]:
                    configs = [json.loads(c) for c in row["configs"].split("|||")]
                    common_configs = self._extract_common_configurations(configs)

                pattern = DeploymentPattern(
                    pattern_id=pattern_id,
                    resource_types=resource_types,
                    frequency=row["frequency"],
                    success_rate=float(row["success_rate"]),
                    average_cost_per_month=float(row["avg_cost"]) if row["avg_cost"] else None,
                    common_configurations=common_configs,
                    environment_distribution={row["environment"]: row["frequency"]},
                    last_seen=row["last_seen"],
                )
                patterns.append(pattern)

            span.set_attribute("patterns_found", len(patterns))
            self._pattern_cache[user_id] = patterns

            logger.info(
                "Deployment patterns analyzed",
                user_id=user_id,
                patterns_count=len(patterns),
            )

            return patterns

    async def get_failure_patterns(self, user_id: str) -> list[FailurePattern]:
        with tracer.start_as_current_span(
            "get_failure_patterns",
            attributes={"user_id": user_id},
        ) as span:
            logger.debug("Analyzing failure patterns", user_id=user_id)

            store = await get_async_store()
            async with store.get_connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT 
                        error_type,
                        COUNT(*) as frequency,
                        string_agg(DISTINCT resource_types::text, '|||') as resource_contexts,
                        string_agg(DISTINCT environment, ',') as environments,
                        string_agg(error_message, ' | ') as messages
                    FROM deployment_outcomes 
                    WHERE user_id = $1 
                      AND success = FALSE 
                      AND error_type IS NOT NULL
                      AND created_at > $2
                    GROUP BY error_type
                    HAVING COUNT(*) >= 2
                    ORDER BY frequency DESC
                    LIMIT 10
                    """,
                    user_id,
                    datetime.utcnow() - timedelta(days=60),
                )

            failure_patterns: list[FailurePattern] = []
            for row in rows:
                resource_contexts = {}
                if row["resource_contexts"]:
                    contexts = [json.loads(c) for c in row["resource_contexts"].split("|||")]
                    resource_contexts = {"resource_types": contexts}

                causes = self._extract_common_causes(row["messages"] or "")
                solutions = self._generate_solutions(row["error_type"])

                pattern = FailurePattern(
                    failure_id=f"{user_id}:{row['error_type']}",
                    error_type=row["error_type"],
                    resource_context=resource_contexts,
                    frequency=row["frequency"],
                    resolution_success_rate=0.7,  # Could be calculated from follow-up deployments
                    common_causes=causes,
                    recommended_solutions=solutions,
                    environments=row["environments"].split(",") if row["environments"] else [],
                )
                failure_patterns.append(pattern)

            span.set_attribute("failure_patterns_found", len(failure_patterns))

            logger.info(
                "Failure patterns analyzed",
                user_id=user_id,
                failure_patterns_count=len(failure_patterns),
            )

            return failure_patterns

    async def get_optimization_insights(self, user_id: str) -> list[CostOptimization]:
        with tracer.start_as_current_span(
            "get_optimization_insights",
            attributes={"user_id": user_id},
        ) as span:
            logger.debug("Analyzing optimization insights", user_id=user_id)

            store = await get_async_store()
            async with store.get_connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT 
                        resource_type,
                        original_config,
                        optimized_config,
                        cost_savings_percentage,
                        performance_impact,
                        COUNT(*) as frequency,
                        AVG(CASE WHEN applied THEN 1.0 ELSE 0.0 END) as adoption_rate,
                        string_agg(DISTINCT environment, ',') as environments
                    FROM cost_optimizations 
                    WHERE user_id = $1 
                      AND created_at > $2
                    GROUP BY resource_type, original_config, optimized_config, 
                             cost_savings_percentage, performance_impact
                    HAVING COUNT(*) >= 1
                    ORDER BY cost_savings_percentage DESC, frequency DESC
                    LIMIT 15
                    """,
                    user_id,
                    datetime.utcnow() - timedelta(days=90),
                )

            optimizations: list[CostOptimization] = []
            for row in rows:
                optimization = CostOptimization(
                    optimization_id=f"{user_id}:{row['resource_type']}:{hash(row['original_config'])}",
                    resource_type=row["resource_type"],
                    original_configuration=json.loads(row["original_config"]),
                    optimized_configuration=json.loads(row["optimized_config"]),
                    cost_savings_percentage=float(row["cost_savings_percentage"]),
                    performance_impact=row["performance_impact"],
                    adoption_rate=float(row["adoption_rate"]),
                    environments=row["environments"].split(",") if row["environments"] else [],
                )
                optimizations.append(optimization)

            span.set_attribute("optimizations_found", len(optimizations))

            logger.info(
                "Optimization insights analyzed",
                user_id=user_id,
                optimizations_count=len(optimizations),
            )

            return optimizations

    async def get_comprehensive_insights(self, user_id: str) -> DeploymentInsights:
        with tracer.start_as_current_span(
            "get_comprehensive_insights",
            attributes={"user_id": user_id},
        ) as span:
            logger.info("Generating comprehensive deployment insights", user_id=user_id)

            import asyncio
            patterns, failures, optimizations = await asyncio.gather(
                self.get_deployment_patterns(user_id),
                self.get_failure_patterns(user_id),
                self.get_optimization_insights(user_id),
            )

            user_preferences = await self._extract_user_preferences(user_id)
            confidence = self._calculate_recommendation_confidence(patterns, failures)

            span.set_attributes({
                "successful_patterns": len(patterns),
                "failure_patterns": len(failures),
                "cost_optimizations": len(optimizations),
                "recommendation_confidence": confidence,
            })

            insights = DeploymentInsights(
                successful_patterns=patterns,
                failure_patterns=failures,
                cost_optimizations=optimizations,
                user_preferences=user_preferences,
                recommendation_confidence=confidence,
            )

            app_insights.track_custom_event(
                "comprehensive_insights_generated",
                {
                    "user_id": user_id,
                    "patterns_count": len(patterns),
                    "failures_count": len(failures),
                    "optimizations_count": len(optimizations),
                    "confidence": confidence,
                },
            )

            return insights

    def _extract_common_configurations(self, configs: list[dict[str, Any]]) -> dict[str, Any]:
        if not configs:
            return {}

        common = {}
        for key in configs[0].keys():
            values = [c.get(key) for c in configs if key in c]
            if len(set(str(v) for v in values)) == 1:
                common[key] = values[0]
            elif len(values) > len(configs) * 0.6:
                value_counts = defaultdict(int)
                for v in values:
                    value_counts[str(v)] += 1
                most_common = max(value_counts.items(), key=lambda x: x[1])
                common[key] = most_common[0]

        return common

    def _extract_common_causes(self, messages: str) -> list[str]:
        causes = []
        message_lower = messages.lower()
        
        if "quota" in message_lower or "limit" in message_lower:
            causes.append("Resource quota or limit exceeded")
        if "permission" in message_lower or "unauthorized" in message_lower:
            causes.append("Insufficient permissions")
        if "network" in message_lower or "connectivity" in message_lower:
            causes.append("Network connectivity issues")
        if "configuration" in message_lower or "invalid" in message_lower:
            causes.append("Invalid resource configuration")
        if "dependency" in message_lower:
            causes.append("Missing resource dependencies")
            
        return causes if causes else ["Unknown cause"]

    def _generate_solutions(self, error_type: str) -> list[str]:
        solutions_map = {
            "QuotaExceeded": [
                "Request quota increase through Azure portal",
                "Use different Azure region with available capacity",
                "Optimize resource sizing to reduce quota usage",
            ],
            "AuthorizationFailed": [
                "Verify service principal has required permissions",
                "Check resource group access policies",
                "Ensure subscription-level permissions are configured",
            ],
            "ResourceNotFound": [
                "Verify dependent resources exist before deployment",
                "Check resource naming and location consistency",
                "Ensure proper deployment order",
            ],
            "NetworkError": [
                "Check network security group rules",
                "Verify subnet configuration and availability",
                "Review firewall and routing settings",
            ],
        }
        
        return solutions_map.get(error_type, [
            "Review error details and Azure documentation",
            "Check resource configuration parameters",
            "Verify dependencies and prerequisites",
        ])

    async def _extract_user_preferences(self, user_id: str) -> dict[str, Any]:
        store = await get_async_store()
        async with store.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    environment,
                    AVG(cost_estimate) as avg_cost_preference,
                    COUNT(*) as deployment_count
                FROM deployment_outcomes 
                WHERE user_id = $1 
                  AND success = TRUE
                  AND created_at > $2
                GROUP BY environment
                """,
                user_id,
                datetime.utcnow() - timedelta(days=60),
            )

        preferences = {
            "preferred_environments": [],
            "cost_consciousness": "medium",
            "deployment_frequency": "moderate",
        }

        if rows:
            env_counts = {row["environment"]: row["deployment_count"] for row in rows}
            preferences["preferred_environments"] = sorted(
                env_counts.keys(), key=lambda x: env_counts[x], reverse=True
            )

            avg_costs = [row["avg_cost_preference"] for row in rows if row["avg_cost_preference"]]
            if avg_costs:
                avg_cost = sum(avg_costs) / len(avg_costs)
                if avg_cost < 100:
                    preferences["cost_consciousness"] = "high"
                elif avg_cost > 500:
                    preferences["cost_consciousness"] = "low"

        return preferences

    def _calculate_recommendation_confidence(
        self, patterns: list[DeploymentPattern], failures: list[FailurePattern]
    ) -> float:
        if not patterns:
            return 0.0

        total_deployments = sum(p.frequency for p in patterns)
        successful_deployments = sum(p.frequency * p.success_rate for p in patterns)
        
        base_confidence = successful_deployments / total_deployments if total_deployments > 0 else 0.0
        
        pattern_diversity = min(len(patterns) / 5.0, 1.0)
        failure_impact = max(0.0, 1.0 - len(failures) / 10.0)
        
        return min(base_confidence * pattern_diversity * failure_impact, 1.0)

    def _invalidate_pattern_cache(self, user_id: str) -> None:
        if user_id in self._pattern_cache:
            del self._pattern_cache[user_id]


_deployment_learning_service: DeploymentLearningService | None = None


async def get_deployment_learning_service() -> DeploymentLearningService:
    global _deployment_learning_service
    if _deployment_learning_service is None:
        _deployment_learning_service = DeploymentLearningService()
        await _deployment_learning_service.initialize()
    return _deployment_learning_service