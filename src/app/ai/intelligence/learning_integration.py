from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.memory.storage import get_async_store
from app.observability.agent_tracing import get_agent_tracer

logger = get_logger(__name__)
tracer = get_agent_tracer("LearningIntegrationService")


@dataclass
class LearningEnhancedRecommendation:
    base_recommendation: dict[str, Any]
    learning_confidence: float
    historical_success_rate: float
    cost_impact_learned: str
    user_adoption_likelihood: float
    similar_patterns_found: int


class LearningIntegrationService:
    def __init__(self) -> None:
        pass

    async def enhance_recommendations_with_learning(
        self,
        user_id: str,
        base_recommendations: list[dict[str, Any]],
        current_resource_types: list[str],
        environment: str,
    ) -> list[LearningEnhancedRecommendation]:
        async with tracer.trace_operation(
            "enhance_recommendations_with_learning",
            {
                "user_id": user_id,
                "recommendations_count": len(base_recommendations),
                "environment": environment,
            },
        ) as span:
            logger.info(
                "Enhancing recommendations with deployment learning",
                user_id=user_id,
                base_recommendations_count=len(base_recommendations),
                current_resources=current_resource_types,
                environment=environment,
            )

            store = await get_async_store()

            user_patterns = await store.get_deployment_patterns(user_id)
            user_optimizations = await store.get_optimization_insights(user_id)
            user_failures = await store.get_failure_insights(user_id)

            enhanced_recommendations = []
            for rec in base_recommendations:
                enhanced = await self._enhance_single_recommendation(
                    rec,
                    user_patterns,
                    user_optimizations,
                    user_failures,
                    current_resource_types,
                    environment,
                )
                enhanced_recommendations.append(enhanced)

            span.set_attributes(
                {
                    "enhanced_recommendations": len(enhanced_recommendations),
                    "user_patterns_analyzed": len(user_patterns),
                    "user_optimizations_analyzed": len(user_optimizations),
                }
            )

            logger.info(
                "Recommendations enhanced with learning data",
                enhanced_count=len(enhanced_recommendations),
                patterns_used=len(user_patterns),
                optimizations_used=len(user_optimizations),
            )

            return enhanced_recommendations

    async def _enhance_single_recommendation(
        self,
        recommendation: dict[str, Any],
        user_patterns: list[dict[str, Any]],
        user_optimizations: list[dict[str, Any]],
        user_failures: list[dict[str, Any]],
        current_resource_types: list[str],
        environment: str,
    ) -> LearningEnhancedRecommendation:
        rec_type = recommendation.get("type", "")

        similar_patterns = [
            p
            for p in user_patterns
            if rec_type in p.get("resource_types", [])
            or any(rt in p.get("resource_types", []) for rt in current_resource_types)
        ]

        historical_success = 0.0
        if similar_patterns:
            success_rates = [p.get("success_rate", 0.0) for p in similar_patterns]
            historical_success = sum(success_rates) / len(success_rates)

        relevant_optimizations = [
            opt
            for opt in user_optimizations
            if opt.get("resource_type") == rec_type and environment in opt.get("environments", [])
        ]

        adoption_likelihood = 0.5
        if relevant_optimizations:
            adoption_rates = [opt.get("adoption_rate", 0.0) for opt in relevant_optimizations]
            adoption_likelihood = sum(adoption_rates) / len(adoption_rates)

        cost_impact = "unknown"
        if relevant_optimizations:
            avg_savings = sum(
                opt.get("cost_savings_percentage", 0.0) for opt in relevant_optimizations
            ) / len(relevant_optimizations)
            if avg_savings > 20:
                cost_impact = "high_savings"
            elif avg_savings > 10:
                cost_impact = "medium_savings"
            else:
                cost_impact = "low_savings"

        relevant_failures = [
            f
            for f in user_failures
            if rec_type in str(f.get("resource_context", {}))
            and environment in f.get("environments", [])
        ]

        learning_confidence = self._calculate_learning_confidence(
            similar_patterns, relevant_optimizations, relevant_failures
        )

        return LearningEnhancedRecommendation(
            base_recommendation=recommendation,
            learning_confidence=learning_confidence,
            historical_success_rate=historical_success,
            cost_impact_learned=cost_impact,
            user_adoption_likelihood=adoption_likelihood,
            similar_patterns_found=len(similar_patterns),
        )

    def _calculate_learning_confidence(
        self,
        similar_patterns: list[dict[str, Any]],
        optimizations: list[dict[str, Any]],
        failures: list[dict[str, Any]],
    ) -> float:
        pattern_confidence = min(len(similar_patterns) / 5.0, 1.0)
        optimization_confidence = min(len(optimizations) / 3.0, 1.0)
        failure_penalty = max(0.0, 1.0 - len(failures) / 10.0)

        base_confidence = (pattern_confidence + optimization_confidence) / 2.0
        return base_confidence * failure_penalty

    async def record_deployment_result_for_learning(
        self,
        user_id: str,
        deployment_id: str,
        resource_types: list[str],
        environment: str,
        success: bool,
        configuration: dict[str, Any],
        recommendations_followed: list[str] | None = None,
        error_details: dict[str, Any] | None = None,
        cost_estimate: float | None = None,
        duration_seconds: int | None = None,
    ) -> None:
        async with tracer.trace_operation(
            "record_deployment_for_learning",
            {
                "user_id": user_id,
                "deployment_id": deployment_id,
                "success": success,
                "environment": environment,
                "recommendations_followed_count": len(recommendations_followed or []),
            },
        ) as span:
            logger.info(
                "Recording deployment result for machine learning",
                user_id=user_id,
                deployment_id=deployment_id,
                success=success,
                environment=environment,
                resource_count=len(resource_types),
                recommendations_followed=len(recommendations_followed or []),
            )

            store = await get_async_store()

            error_type = None
            error_message = None
            if error_details:
                error_type = error_details.get("type")
                error_message = error_details.get("message")

            await store.record_deployment_outcome(
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

            if recommendations_followed:
                await self._record_recommendation_adoption(
                    user_id, deployment_id, recommendations_followed, success
                )

            span.set_attributes(
                {
                    "learning_recorded": True,
                    "recommendations_tracked": len(recommendations_followed or []),
                }
            )

    async def _record_recommendation_adoption(
        self,
        user_id: str,
        deployment_id: str,
        recommendations_followed: list[str],
        deployment_success: bool,
    ) -> None:
        from app.memory.deployment_learning import get_deployment_learning_service

        learning_service = await get_deployment_learning_service()

        for rec_type in recommendations_followed:
            await learning_service.record_cost_optimization(
                user_id=user_id,
                resource_type=rec_type,
                original_config={"recommendation": "not_followed"},
                optimized_config={"recommendation": "followed"},
                cost_savings_percentage=0.0,
                performance_impact="unknown",
                environment="unknown",
                applied=deployment_success,
            )

    async def get_personalized_insights(self, user_id: str, current_request: str) -> dict[str, Any]:
        async with tracer.trace_operation(
            "get_personalized_insights", {"user_id": user_id}
        ) as span:
            logger.debug("Generating personalized deployment insights", user_id=user_id)

            store = await get_async_store()
            patterns = await store.get_deployment_patterns(user_id)
            optimizations = await store.get_optimization_insights(user_id)
            failures = await store.get_failure_insights(user_id)

            insights = {
                "deployment_velocity": self._analyze_deployment_velocity(patterns),
                "cost_optimization_opportunities": self._identify_cost_opportunities(optimizations),
                "risk_factors": self._assess_risk_factors(failures),
                "success_patterns": self._extract_success_patterns(patterns),
                "personalized_recommendations": self._generate_personalized_recommendations(
                    patterns, optimizations, current_request
                ),
            }

            span.set_attributes(
                {
                    "insights_generated": len(insights),
                    "patterns_analyzed": len(patterns),
                    "optimizations_analyzed": len(optimizations),
                    "failures_analyzed": len(failures),
                }
            )

            logger.info(
                "Personalized insights generated",
                user_id=user_id,
                insight_categories=len(insights),
                data_points_analyzed=len(patterns) + len(optimizations) + len(failures),
            )

            return insights

    def _analyze_deployment_velocity(self, patterns: list[dict[str, Any]]) -> dict[str, Any]:
        if not patterns:
            return {"status": "insufficient_data", "velocity": "unknown"}

        total_deployments = sum(p.get("frequency", 0) for p in patterns)
        if total_deployments > 50:
            return {"status": "high_velocity", "deployments_analyzed": total_deployments}
        elif total_deployments > 15:
            return {"status": "moderate_velocity", "deployments_analyzed": total_deployments}
        else:
            return {"status": "low_velocity", "deployments_analyzed": total_deployments}

    def _identify_cost_opportunities(
        self, optimizations: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        opportunities = []
        for opt in optimizations:
            if opt.get("cost_savings_percentage", 0) > 15 and opt.get("adoption_rate", 0) < 0.5:
                opportunities.append(
                    {
                        "resource_type": opt.get("resource_type"),
                        "potential_savings": opt.get("cost_savings_percentage"),
                        "adoption_barrier": "low_adoption_rate",
                        "recommendation": "Review performance impact and consider gradual adoption",
                    }
                )
        return opportunities

    def _assess_risk_factors(self, failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        risk_factors = []
        for failure in failures:
            if failure.get("frequency", 0) > 3:
                risk_factors.append(
                    {
                        "risk_type": failure.get("error_type"),
                        "frequency": failure.get("frequency"),
                        "environments": failure.get("environments", []),
                        "mitigation": failure.get("recommended_solutions", [])[:2],
                    }
                )
        return risk_factors

    def _extract_success_patterns(self, patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        success_patterns = []
        for pattern in patterns:
            if pattern.get("success_rate", 0) > 0.9 and pattern.get("frequency", 0) > 5:
                success_patterns.append(
                    {
                        "resource_combination": pattern.get("resource_types", []),
                        "success_rate": pattern.get("success_rate"),
                        "frequency": pattern.get("frequency"),
                        "common_config": pattern.get("common_configurations", {}),
                    }
                )
        return success_patterns[:5]

    def _generate_personalized_recommendations(
        self,
        patterns: list[dict[str, Any]],
        optimizations: list[dict[str, Any]],
        current_request: str,
    ) -> list[str]:
        recommendations = []

        high_success_resources = set()
        for pattern in patterns:
            if pattern.get("success_rate", 0) > 0.95:
                high_success_resources.update(pattern.get("resource_types", []))

        if high_success_resources:
            recommendations.append(
                f"Consider using {', '.join(list(high_success_resources)[:3])} - "
                "high success rate in your history"
            )

        high_value_optimizations = [
            opt for opt in optimizations if opt.get("cost_savings_percentage", 0) > 20
        ]
        if high_value_optimizations:
            top_opt = high_value_optimizations[0]
            recommendations.append(
                f"Apply {top_opt.get('resource_type')} optimization for "
                f"{top_opt.get('cost_savings_percentage'):.1f}% cost savings"
            )

        return recommendations


_learning_integration_service: LearningIntegrationService | None = None


async def get_learning_integration_service() -> LearningIntegrationService:
    global _learning_integration_service
    if _learning_integration_service is None:
        _learning_integration_service = LearningIntegrationService()
    return _learning_integration_service
