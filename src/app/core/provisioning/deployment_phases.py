from __future__ import annotations

import re
from enum import Enum
from typing import Any, cast

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.observability.app_insights import app_insights

from .execution_context import ProvisionContext, ProvisioningPhase

tracer = trace.get_tracer(__name__)


class DeploymentIntent(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    QUERY = "query"
    EXECUTE = "execute"
    PLAN = "plan"


class DeploymentPhaseManager:
    def __init__(self) -> None:
        self._phase_patterns = {
            DeploymentIntent.EXECUTE: [
                r"\b(proceed|continue|execute|deploy|run|go ahead|yes|confirm)\b",
                r"\b(implement|apply|start)\b",
                r"\b(do it|make it happen)\b",
            ],
            DeploymentIntent.PLAN: [
                r"\b(plan|preview|show|what would|dry.?run)\b",
                r"\b(estimate|cost|price)\b",
                r"\b(validate|check|verify)\b",
            ],
            DeploymentIntent.CREATE: [
                r"\b(create|provision|deploy|setup|build)\b",
                r"\b(new|fresh|initialize)\b",
                r"\b(spin up|bring up|launch)\b",
            ],
            DeploymentIntent.UPDATE: [
                r"\b(update|modify|change|edit|alter)\b",
                r"\b(scale|resize|reconfigure)\b",
                r"\b(upgrade|improve|enhance)\b",
            ],
            DeploymentIntent.DELETE: [
                r"\b(delete|remove|destroy|tear down|cleanup)\b",
                r"\b(stop|shutdown|terminate)\b",
                r"\b(decommission|retire)\b",
            ],
            DeploymentIntent.QUERY: [
                r"\b(show|list|get|describe|status)\b",
                r"\b(what|how|where|when)\b",
                r"\b(info|information|details)\b",
            ],
        }

        self._resource_keywords = [
            "webapp",
            "web app",
            "app service",
            "storage",
            "database",
            "sql",
            "aks",
            "kubernetes",
            "container",
            "vm",
            "virtual machine",
            "keyvault",
            "key vault",
            "redis",
            "cosmos",
            "service bus",
            "function",
            "logic app",
            "api management",
            "front door",
        ]

    def detect_intent(
        self, request_text: str, conversation_context: list[dict[str, str]] | None = None
    ) -> DeploymentIntent:
        with tracer.start_as_current_span("deployment_phase_detect_intent") as span:
            request_lower = request_text.lower()

            span.set_attributes(
                {
                    "request.length": len(request_text),
                    "request.has_context": bool(conversation_context),
                    "request.context_length": len(conversation_context or []),
                }
            )

            intent_scores: dict[DeploymentIntent, dict[str, Any]] = {}

            for intent, patterns in self._phase_patterns.items():
                score = 0
                matched_patterns: list[str] = []

                for pattern in patterns:
                    matches = re.findall(pattern, request_lower, re.IGNORECASE)
                    if matches:
                        score += len(matches)
                        matched_patterns.extend(matches)

                if score > 0:
                    intent_scores[intent] = {"score": score, "patterns": matched_patterns}

            if not intent_scores:
                detected_intent = DeploymentIntent.CREATE
                confidence = 0.3
                reason = "No clear patterns found, defaulting to CREATE"
            else:

                def get_score(intent: DeploymentIntent) -> float:
                    return float(intent_scores[intent]["score"])

                best_intent = max(intent_scores.keys(), key=get_score)
                best_score = get_score(best_intent)
                confidence = min(best_score / 5.0, 1.0)
                detected_intent = best_intent
                reason = f"Matched patterns: {intent_scores[best_intent]['patterns']}"

            if conversation_context:
                context_boost = self._analyze_conversation_context(conversation_context)
                if context_boost:
                    detected_intent = context_boost
                    confidence = min(confidence + 0.2, 1.0)
                    reason += " (boosted by conversation context)"

            scores_str = ", ".join(
                [
                    f"{(k.value if hasattr(k, 'value') else str(k))}:{v['score']}"
                    for k, v in intent_scores.items()
                ]
            )

            span.set_attributes(
                {
                    "intent.detected": detected_intent.value,
                    "intent.confidence": confidence,
                    "intent.reason": reason,
                    "intent.scores": scores_str,
                }
            )
            span.set_status(Status(StatusCode.OK))

            app_insights.track_custom_event(
                "deployment_intent_detected",
                {
                    "detected_intent": detected_intent.value,
                    "reason": reason,
                    "request_preview": request_text[:100],
                },
                {"confidence": confidence, "request_length": len(request_text)},
            )

            return detected_intent

    def _analyze_conversation_context(
        self, conversation_context: list[dict[str, str]]
    ) -> DeploymentIntent | None:
        if not conversation_context:
            return None

        recent_messages = conversation_context[-3:]

        for message in reversed(recent_messages):
            content = message.get("content", "").lower()

            if any(word in content for word in ["plan", "preview", "dry-run"]):
                if any(word in content for word in ["proceed", "execute", "apply"]):
                    return DeploymentIntent.EXECUTE

        return None

    def determine_provisioning_phase(self, context: ProvisionContext) -> ProvisioningPhase:
        with tracer.start_as_current_span("deployment_phase_determine_provisioning") as span:
            current_phase_value = (
                context.current_phase.value
                if isinstance(context.current_phase, ProvisioningPhase)
                else str(context.current_phase)
            )

            span.set_attributes(
                {
                    "context.user_id": context.user_id,
                    "context.correlation_id": context.correlation_id,
                    "context.current_phase": current_phase_value,
                    "context.has_parsed_resources": len(context.parsed_resources) > 0,
                    "context.has_deployment_plan": bool(context.deployment_plan),
                }
            )

            intent = self.detect_intent(context.request_text, context.conversation_context)

            if intent == DeploymentIntent.EXECUTE:
                if not context.parsed_resources:
                    phase = ProvisioningPhase.PARSING
                elif not context.deployment_plan:
                    phase = ProvisioningPhase.PLANNING
                else:
                    phase = ProvisioningPhase.EXECUTION
            elif intent == DeploymentIntent.PLAN:
                if not context.parsed_resources:
                    phase = ProvisioningPhase.PARSING
                else:
                    phase = ProvisioningPhase.PLANNING
            else:
                phase = ProvisioningPhase.VALIDATION

            intent_value = intent.value if hasattr(intent, "value") else str(intent)
            phase_value = phase.value if hasattr(phase, "value") else str(phase)

            span.set_attributes(
                {
                    "phase.detected_intent": intent_value,
                    "phase.determined": phase_value,
                    "phase.reasoning": (
                        f"Intent {intent_value} with "
                        f"parsed_resources={len(context.parsed_resources)}, "
                        f"has_plan={bool(context.deployment_plan)}"
                    ),
                }
            )
            span.set_status(Status(StatusCode.OK))

            app_insights.track_custom_event(
                "provisioning_phase_determined",
                {
                    "user_id": context.user_id,
                    "correlation_id": context.correlation_id,
                    "detected_intent": intent_value,
                    "determined_phase": phase_value,
                },
                {
                    "parsed_resources_count": len(context.parsed_resources),
                    "has_deployment_plan": int(bool(context.deployment_plan)),
                },
            )

            return phase

    def validate_phase_transition(
        self, current_phase: ProvisioningPhase, next_phase: ProvisioningPhase
    ) -> bool:
        with tracer.start_as_current_span("deployment_phase_validate_transition") as span:
            valid_transitions = {
                ProvisioningPhase.VALIDATION: [ProvisioningPhase.PARSING],
                ProvisioningPhase.PARSING: [
                    ProvisioningPhase.PLANNING,
                    ProvisioningPhase.VALIDATION,
                ],
                ProvisioningPhase.PLANNING: [
                    ProvisioningPhase.EXECUTION,
                    ProvisioningPhase.PARSING,
                ],
                ProvisioningPhase.EXECUTION: [
                    ProvisioningPhase.FALLBACK,
                    ProvisioningPhase.COMPLETION,
                    ProvisioningPhase.PLANNING,
                ],
                ProvisioningPhase.FALLBACK: [
                    ProvisioningPhase.COMPLETION,
                    ProvisioningPhase.EXECUTION,
                ],
                ProvisioningPhase.COMPLETION: [],
            }

            is_valid = next_phase in valid_transitions.get(current_phase, [])

            span.set_attributes(
                {
                    "transition.current_phase": current_phase.value,
                    "transition.next_phase": next_phase.value,
                    "transition.is_valid": is_valid,
                    "transition.allowed_transitions": [
                        p.value for p in valid_transitions.get(current_phase, [])
                    ],
                }
            )

            if is_valid:
                span.set_status(Status(StatusCode.OK))
            else:
                span.set_status(
                    Status(
                        StatusCode.ERROR,
                        f"Invalid phase transition from {current_phase.value} to "
                        f"{next_phase.value}",
                    )
                )

            return is_valid

    def get_phase_requirements(self, phase: ProvisioningPhase) -> dict[str, Any]:
        requirements = {
            ProvisioningPhase.VALIDATION: {
                "required_fields": ["request_text", "user_id"],
                "optional_fields": ["subscription_id", "resource_group"],
                "description": "Validate basic request parameters",
            },
            ProvisioningPhase.PARSING: {
                "required_fields": ["request_text"],
                "optional_fields": ["conversation_context"],
                "description": "Parse natural language into structured resource requirements",
            },
            ProvisioningPhase.PLANNING: {
                "required_fields": ["parsed_resources"],
                "optional_fields": ["cost_optimization"],
                "description": "Generate deployment plan with dependencies and ordering",
            },
            ProvisioningPhase.EXECUTION: {
                "required_fields": ["deployment_plan", "subscription_id"],
                "optional_fields": ["dry_run"],
                "description": "Execute deployment using selected strategy",
            },
            ProvisioningPhase.FALLBACK: {
                "required_fields": ["attempted_strategies"],
                "optional_fields": [],
                "description": "Attempt fallback strategy when primary fails",
            },
            ProvisioningPhase.COMPLETION: {
                "required_fields": ["execution_result"],
                "optional_fields": [],
                "description": "Finalize deployment and return results",
            },
        }

        return requirements.get(phase, {})

    def get_phase_metrics(self, phase: ProvisioningPhase) -> dict[str, Any]:
        with tracer.start_as_current_span("deployment_phase_get_metrics") as span:
            metrics = {
                "phase": phase.value,
                "timestamp": span.get_span_context().span_id,
                "requirements": self.get_phase_requirements(phase),
            }

            requirements = cast("dict[str, Any]", metrics["requirements"])
            span.set_attributes(
                {
                    "phase.name": phase.value,
                    "phase.required_fields": len(requirements.get("required_fields", [])),
                    "phase.optional_fields": len(requirements.get("optional_fields", [])),
                }
            )
            span.set_status(Status(StatusCode.OK))

            return metrics
