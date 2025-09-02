from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from app.core.logging import get_logger
from app.core.plugins.base import PluginContext
from app.core.plugins.manager import PluginManager
from app.core.provisioning import ExecutionResult, ProvisionContext, ProvisioningOrchestrator
from app.memory.agent_persistence import get_agent_memory
from app.observability.app_insights import app_insights
from app.observability.distributed_tracing import get_service_tracer
from app.services.deployment_preview import DeploymentPreviewService

tracer = trace.get_tracer(__name__)
logger = get_logger(__name__)


class VectorEnhancedProvisioningTool:
    def __init__(self, plugin_manager: PluginManager, orchestrator: ProvisioningOrchestrator):
        self.plugin_manager = plugin_manager
        self.orchestrator = orchestrator
        self.preview_service = DeploymentPreviewService()
        self.service_tracer = get_service_tracer("vector_enhanced_provisioning")
        self.logger = logger.bind(component="vector_provisioning")

        self._vector_plugin_name = "vector_database"

    async def intelligent_provision_with_context(
        self,
        request_text: str,
        user_id: str,
        correlation_id: str,
        dry_run: bool = True,
        environment: str = "dev",
        **kwargs: Any,
    ) -> ExecutionResult:
        async with self.service_tracer.start_distributed_span(
            operation_name="vector_enhanced_provision",
            correlation_id=correlation_id,
            user_id=user_id,
            attributes={
                "provision.request_length": len(request_text),
                "provision.dry_run": dry_run,
                "provision.environment": environment,
            },
        ) as span:
            start_time = datetime.now(UTC)

            try:
                historical_context = await self._get_provisioning_context(
                    request_text, user_id, correlation_id, span
                )

                enhanced_context = await self._create_enhanced_provision_context(
                    request_text=request_text,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    dry_run=dry_run,
                    environment=environment,
                    historical_context=historical_context,
                    **kwargs,
                )

                # Generate preview response if dry_run is enabled
                if dry_run:
                    result = await self._generate_preview_with_context(
                        enhanced_context, historical_context, span
                    )
                else:
                    result = await self.orchestrator.execute_with_fallback(enhanced_context)

                await self._index_provisioning_outcome(
                    enhanced_context, result, historical_context, span
                )

                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                result.execution_time_ms = execution_time

                span.set_attributes(
                    {
                        "provision.execution_time_ms": execution_time,
                        "provision.success": result.success,
                        "provision.strategy_used": result.strategy_used,
                        "provision.context_items": len(
                            historical_context.get("semantic_matches", [])
                        ),
                    }
                )

                app_insights.track_custom_event(
                    "vector_enhanced_provision_completed",
                    {
                        "user_id": user_id,
                        "correlation_id": correlation_id,
                        "strategy_used": result.strategy_used,
                        "environment": environment,
                    },
                    {
                        "execution_time_ms": execution_time,
                        "context_items_found": len(historical_context.get("semantic_matches", [])),
                    },
                )

                span.set_status(Status(StatusCode.OK))
                return result

            except Exception as e:
                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))

                app_insights.track_exception(
                    e,
                    {
                        "user_id": user_id,
                        "correlation_id": correlation_id,
                        "operation": "vector_enhanced_provision",
                    },
                )

                self.logger.error(
                    "Vector-enhanced provisioning failed",
                    user_id=user_id,
                    correlation_id=correlation_id,
                    error=str(e),
                    exc_info=True,
                )

                return ExecutionResult.failure_result(
                    strategy="vector_enhanced_provision",
                    error=str(e),
                    execution_time=execution_time,
                )

    async def _get_provisioning_context(
        self, request_text: str, user_id: str, correlation_id: str, span: Span
    ) -> dict[str, Any]:
        with tracer.start_as_current_span("get_provisioning_context") as context_span:
            try:
                plugin_context = PluginContext(
                    plugin_name=self._vector_plugin_name,
                    correlation_id=correlation_id,
                    execution_context={
                        "operation": "get_relevant_context",
                        "query": request_text,
                        "context_types": ["deployment", "provisioning", "resource"],
                    },
                    user_context={"user_id": user_id},
                )

                plugin_result = await self.plugin_manager.execute_plugin(
                    self._vector_plugin_name, plugin_context
                )

                if plugin_result.success:
                    context_data = cast(dict[str, Any], plugin_result.result)

                    context_span.set_attributes(
                        {
                            "context.semantic_matches": len(
                                context_data.get("semantic_matches", [])
                            ),
                            "context.stored_contexts": len(context_data.get("stored_contexts", [])),
                            "context.plugin_execution_time": plugin_result.execution_time_ms,
                        }
                    )

                    return context_data
                else:
                    context_span.set_attribute(
                        "context.plugin_error", str(plugin_result.error_message or "Unknown error")
                    )
                    self.logger.warning(
                        "Failed to get provisioning context", error=plugin_result.error_message
                    )
                    return {"semantic_matches": [], "stored_contexts": []}

            except Exception as e:
                context_span.record_exception(e)
                self.logger.error("Error getting provisioning context", error=str(e), exc_info=True)
                return {"semantic_matches": [], "stored_contexts": []}

    async def _create_enhanced_provision_context(
        self,
        request_text: str,
        user_id: str,
        correlation_id: str,
        dry_run: bool,
        environment: str,
        historical_context: dict[str, Any],
        **kwargs: Any,
    ) -> ProvisionContext:
        with tracer.start_as_current_span("create_enhanced_context") as context_span:
            from app.ai.nlu import parse_provision_request

            nlu_result = parse_provision_request(request_text)

            extracted_resource_group = nlu_result.parameters.get("resource_group", "")
            extracted_location = nlu_result.parameters.get("location", "westeurope")
            extracted_name = nlu_result.resource_name

            context_span.set_attributes(
                {
                    "nlu.resource_type": nlu_result.resource_type,
                    "nlu.resource_name": extracted_name or "unnamed",
                    "nlu.resource_group": extracted_resource_group or "not_extracted",
                    "nlu.location": extracted_location,
                    "nlu.confidence": nlu_result.confidence,
                }
            )

            similar_deployments = historical_context.get("semantic_matches", [])
            stored_contexts = historical_context.get("stored_contexts", [])

            context_span.set_attributes(
                {
                    "context.similar_deployments": len(similar_deployments),
                    "context.stored_contexts": len(stored_contexts),
                }
            )

            enhanced_metadata = {
                "vector_enhanced": True,
                "similar_deployments_found": len(similar_deployments),
                "historical_context_items": len(stored_contexts),
                "context_generation_timestamp": datetime.now(UTC).isoformat(),
                "nlu_resource_type": nlu_result.resource_type,
                "nlu_confidence": nlu_result.confidence,
                "nlu_extracted_params": nlu_result.parameters,
            }

            learned_patterns = []
            risk_factors = []
            optimization_hints = []

            for deployment in similar_deployments[:5]:
                metadata = deployment.get("metadata", {})

                if metadata.get("success"):
                    learned_patterns.append(
                        {
                            "pattern": deployment.get("summary", "")[:200],
                            "success_score": deployment.get("score", 0.0),
                            "resource_types": metadata.get("resource_types", []),
                        }
                    )
                    optimization_hints.append("Consider pattern from successful similar deployment")
                else:
                    risk_factors.append(
                        {
                            "risk": deployment.get("summary", "")[:200],
                            "failure_reason": metadata.get("error_message", "Unknown"),
                            "similarity_score": deployment.get("score", 0.0),
                        }
                    )

            enhanced_metadata.update(
                {
                    "learned_patterns": learned_patterns,
                    "risk_factors": risk_factors,
                    "optimization_hints": optimization_hints,
                }
            )

            conversation_context = []
            for ctx in stored_contexts[:3]:
                conversation_context.append(
                    {
                        "context_key": ctx.get("context_key", ""),
                        "agent_name": ctx.get("agent_name", ""),
                        "updated_at": ctx.get("updated_at", ""),
                    }
                )

            final_resource_group = kwargs.get("resource_group") or extracted_resource_group
            final_location = kwargs.get("location") or extracted_location
            final_name_prefix = kwargs.get("name_prefix") or extracted_name or "app"

            context = ProvisionContext(  # type: ignore[call-arg]
                request_text=request_text,
                user_id=user_id,
                correlation_id=correlation_id,
                dry_run=dry_run,
                environment=environment,
                name_prefix=final_name_prefix,
                subscription_id=kwargs.get("subscription_id", ""),
                resource_group=final_resource_group,
                location=final_location,
                tags=kwargs.get("tags", {}),
                execution_metadata=enhanced_metadata,
                conversation_context=conversation_context,
            )

            return context

    async def _index_provisioning_outcome(
        self,
        context: ProvisionContext,
        result: ExecutionResult,
        historical_context: dict[str, Any],
        span: Span,
    ) -> None:
        with tracer.start_as_current_span("index_provisioning_outcome") as index_span:
            try:
                outcome_data = {
                    "request_text": context.request_text,
                    "user_id": context.user_id,
                    "environment": context.environment,
                    "strategy_used": result.strategy_used,
                    "success": result.success,
                    "error_message": result.error_message,
                    "execution_time_ms": result.execution_time_ms,
                    "resources_affected": result.resources_affected,
                    "warnings": result.warnings,
                    "dry_run": context.dry_run,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "historical_context_used": {
                        "similar_deployments": len(historical_context.get("semantic_matches", [])),
                        "stored_contexts": len(historical_context.get("stored_contexts", [])),
                    },
                }

                plugin_context = PluginContext(
                    plugin_name=self._vector_plugin_name,
                    correlation_id=context.correlation_id,
                    execution_context={
                        "operation": "index_resource",
                        "resource_data": outcome_data,
                        "resource_type": f"provisioning_outcome_{context.environment}",
                        "resource_id": context.correlation_id,
                    },
                )

                plugin_result = await self.plugin_manager.execute_plugin(
                    self._vector_plugin_name, plugin_context
                )

                if plugin_result.success:
                    index_span.set_attributes(
                        {
                            "indexing.success": True,
                            "indexing.indexed_id": plugin_result.result.get("indexed_id"),
                        }
                    )

                    memory = await get_agent_memory()
                    await memory.store_execution_context(
                        user_id=context.user_id,
                        correlation_id=context.correlation_id,
                        context_data=outcome_data,
                    )

                    self.logger.info(
                        "Provisioning outcome indexed and stored",
                        user_id=context.user_id,
                        correlation_id=context.correlation_id,
                        success=result.success,
                    )
                else:
                    index_span.set_attribute("indexing.success", False)
                    self.logger.warning(
                        "Failed to index provisioning outcome", error=plugin_result.error_message
                    )

            except Exception as e:
                index_span.record_exception(e)
                self.logger.error(
                    "Error indexing provisioning outcome", error=str(e), exc_info=True
                )

    async def get_provisioning_recommendations(
        self, request_text: str, user_id: str, environment: str = "dev"
    ) -> dict[str, Any]:
        async with self.service_tracer.start_distributed_span(
            operation_name="get_provisioning_recommendations",
            correlation_id=f"rec_{user_id}_{hash(request_text)}",
            user_id=user_id,
            attributes={
                "recommendations.request_length": len(request_text),
                "recommendations.environment": environment,
            },
        ) as span:
            try:
                plugin_context = PluginContext(
                    plugin_name=self._vector_plugin_name,
                    correlation_id=f"rec_{user_id}_{hash(request_text)}",
                    execution_context={
                        "operation": "semantic_search",
                        "query": request_text,
                        "limit": 10,
                        "threshold": 0.6,
                    },
                    user_context={"user_id": user_id},
                )

                plugin_result = await self.plugin_manager.execute_plugin(
                    self._vector_plugin_name, plugin_context
                )

                if not plugin_result.success:
                    raise RuntimeError(f"Vector plugin error: {plugin_result.error_message}")

                similar_requests = cast(list[dict[str, Any]], plugin_result.result)

                recommendations: dict[str, Any] = {
                    "request_analysis": request_text,
                    "environment": environment,
                    "similar_deployments": len(similar_requests),
                    "recommendations": [],
                    "risk_assessment": "low",
                    "best_practices": [],
                    "estimated_resources": [],
                    "generated_at": datetime.now(UTC).isoformat(),
                }

                success_count = 0
                failure_count = 0

                for req in similar_requests:
                    metadata = req.get("metadata", {})
                    if metadata.get("success"):
                        success_count += 1
                        recommendations_list = cast(
                            list[dict[str, Any]], recommendations["recommendations"]
                        )
                        recommendations_list.append(
                            {
                                "type": "success_pattern",
                                "confidence": req.get("score", 0.0),
                                "description": (
                                    f"Similar deployment succeeded: "
                                    f"{req.get('summary', '')[:100]}"
                                ),
                                "resources": metadata.get("resources_affected", []),
                            }
                        )
                    else:
                        failure_count += 1
                        recommendations_list = cast(
                            list[dict[str, Any]], recommendations["recommendations"]
                        )
                        recommendations_list.append(
                            {
                                "type": "risk_warning",
                                "confidence": req.get("score", 0.0),
                                "description": (
                                    f"Similar deployment failed: "
                                    f"{metadata.get('error_message', 'Unknown error')[:100]}"
                                ),
                                "mitigation": "Review configuration carefully before deployment",
                            }
                        )

                if failure_count > success_count:
                    recommendations["risk_assessment"] = "high"
                elif failure_count > 0:
                    recommendations["risk_assessment"] = "medium"

                recommendations["best_practices"] = [
                    f"Based on {len(similar_requests)} similar deployments",
                    (
                        f"Success rate: {success_count}/"
                        f"{len(similar_requests) if similar_requests else 0}"
                    ),
                    "Review resource sizing and configuration patterns",
                    f"Test in {environment} environment before production",
                ]

                span.set_attributes(
                    {
                        "recommendations.similar_deployments": len(similar_requests),
                        "recommendations.success_count": success_count,
                        "recommendations.failure_count": failure_count,
                        "recommendations.risk_level": recommendations["risk_assessment"],
                    }
                )

                return recommendations

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                self.logger.error(
                    "Failed to get provisioning recommendations", error=str(e), exc_info=True
                )

                return {
                    "request_analysis": request_text,
                    "environment": environment,
                    "error": str(e),
                    "recommendations": [],
                    "risk_assessment": "unknown",
                    "generated_at": datetime.now(UTC).isoformat(),
                }

    async def _generate_preview_with_context(
        self, context: ProvisionContext, historical_context: dict[str, Any], span: Span
    ) -> ExecutionResult:
        with tracer.start_as_current_span("generate_preview_with_context") as preview_span:
            try:
                from app.ai.nlu import parse_provision_request

                preview_span.set_attributes(
                    {
                        "preview.user_id": context.user_id,
                        "preview.correlation_id": context.correlation_id,
                        "preview.environment": context.environment,
                        "preview.similar_deployments": len(
                            historical_context.get("semantic_matches", [])
                        ),
                        "preview.stored_contexts": len(
                            historical_context.get("stored_contexts", [])
                        ),
                    }
                )

                # Parse the request for preview generation
                nlu_result = parse_provision_request(context.request_text)

                # Generate enhanced preview with historical context
                preview_response = await self.preview_service.generate_preview_response(
                    nlu_result=nlu_result,
                    subscription_id=context.subscription_id or "",
                    resource_group=context.resource_group,
                    location=context.location,
                    environment=context.environment,
                )

                # Enhance preview with vector database insights
                enhanced_preview = await self._enhance_preview_with_insights(
                    preview_response, historical_context, nlu_result
                )

                preview_span.set_attributes(
                    {"preview.success": True, "preview.response_length": len(enhanced_preview)}
                )

                self.logger.info(
                    "Vector-enhanced preview generated successfully",
                    user_id=context.user_id,
                    correlation_id=context.correlation_id,
                    environment=context.environment,
                    response_length=len(enhanced_preview),
                )

                return ExecutionResult.success_result(
                    strategy="preview_generation",
                    data={"preview_response": enhanced_preview},
                    execution_time=0.0,
                )

            except Exception as e:
                preview_span.record_exception(e)
                preview_span.set_status(Status(StatusCode.ERROR, str(e)))

                self.logger.error(
                    "Preview generation failed",
                    user_id=context.user_id,
                    correlation_id=context.correlation_id,
                    error=str(e),
                    exc_info=True,
                )

                return ExecutionResult.failure_result(
                    strategy="preview_generation",
                    error=f"Preview generation failed: {str(e)}",
                    execution_time=0.0,
                )

    async def _enhance_preview_with_insights(
        self, base_preview: str, historical_context: dict[str, Any], nlu_result: Any
    ) -> str:
        """Enhance the preview with insights from vector database and historical context."""

        similar_deployments = historical_context.get("semantic_matches", [])
        stored_contexts = historical_context.get("stored_contexts", [])

        # Build insights section
        insights_section = []

        if similar_deployments:
            insights_section.append("### AI-Powered Deployment Insights")
            insights_section.append(
                f"Found {len(similar_deployments)} similar deployments in history:"
            )

            success_count = sum(
                1
                for dep in similar_deployments[:5]
                if dep.get("metadata", {}).get("success", False)
            )
            failure_count = len(similar_deployments[:5]) - success_count

            insights_section.append(
                f"- Success rate: {success_count}/"
                f"{len(similar_deployments[:5])} recent attempts"
            )

            if success_count > 0:
                insights_section.append("- Recommended patterns from successful deployments:")
                for dep in similar_deployments[:3]:
                    if dep.get("metadata", {}).get("success"):
                        summary = dep.get("summary", "")[:100]
                        if summary:
                            insights_section.append(f"  * {summary}")

            if failure_count > 0:
                insights_section.append("- Risk factors identified from failed deployments:")
                for dep in similar_deployments[:2]:
                    if not dep.get("metadata", {}).get("success", False):
                        error = dep.get("metadata", {}).get("error_message", "Unknown error")[:100]
                        if error:
                            insights_section.append(f"  * Avoid: {error}")

            insights_section.append("")

        if stored_contexts:
            insights_section.append("### Conversation Context")
            insights_section.append(
                f"Leveraging {len(stored_contexts)} stored conversation contexts "
                "for improved accuracy."
            )
            insights_section.append("")

        if not similar_deployments and not stored_contexts:
            insights_section.append("### First-Time Deployment")
            insights_section.append(
                "This appears to be your first deployment of this type. "
                "The system will store this deployment for future reference "
                "to provide better recommendations."
            )
            insights_section.append("")

        # Insert insights after the cost estimate section
        lines = base_preview.split("\n")

        # Find where to insert insights (after cost estimate, before infrastructure code)
        insert_index = len(lines)
        for i, line in enumerate(lines):
            if "Infrastructure as Code" in line or "Bicep Template" in line:
                insert_index = i
                break

        # Insert the insights
        if insights_section:
            lines[insert_index:insert_index] = insights_section

        return "\n".join(lines)
