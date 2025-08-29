from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class DeploymentPhase(Enum):
    PREVIEW = "preview"
    EXECUTE = "execute"


@dataclass
class DeploymentState:
    deployment_id: str
    user_id: str
    resource_spec: dict[str, Any]
    bicep_template: str
    terraform_config: str
    cost_estimate: dict[str, Any]
    what_if_analysis: str
    resource_group: str
    location: str
    subscription_id: str
    created_at: datetime
    expires_at: datetime

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "user_id": self.user_id,
            "resource_spec": self.resource_spec,
            "bicep_template": self.bicep_template,
            "terraform_config": self.terraform_config,
            "cost_estimate": self.cost_estimate,
            "what_if_analysis": self.what_if_analysis,
            "resource_group": self.resource_group,
            "location": self.location,
            "subscription_id": self.subscription_id,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeploymentState:
        return cls(
            deployment_id=data["deployment_id"],
            user_id=data["user_id"],
            resource_spec=data["resource_spec"],
            bicep_template=data["bicep_template"],
            terraform_config=data["terraform_config"],
            cost_estimate=data["cost_estimate"],
            what_if_analysis=data["what_if_analysis"],
            resource_group=data["resource_group"],
            location=data["location"],
            subscription_id=data["subscription_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
        )


class DeploymentPhaseDetector:
    """Detects whether user input is requesting preview or deployment execution."""
    
    CONFIRMATION_PATTERNS = [
        r'\b(proceed)\b',
        r'\b(confirm)\b',
        r'\b(execute)\b',
        r'\b(yes,?\s*deploy)\b',
        r'\b(go\s*ahead)\b',
        r'\b(confirmed?)\b',
        r'\b(proceed\s*with\s*deployment)\b',
        r'\b(execute\s*deployment)\b',
        r'\b(deploy\s*now)\b',
        r'\b(deploy\s*it)\b',
    ]
    
    @classmethod
    def detect_phase(cls, user_input: str, conversation_context: list[dict] | None = None) -> DeploymentPhase:
        """
        Detect if user is requesting preview or execution phase.
        
        Args:
            user_input: The user's message
            conversation_context: Recent conversation messages for context
            
        Returns:
            DeploymentPhase.PREVIEW or DeploymentPhase.EXECUTE
        """
        input_lower = user_input.lower().strip()
        
        logger.info(
            "Phase detection starting",
            user_input=user_input[:100],
            has_conversation_context=conversation_context is not None,
            context_length=len(conversation_context) if conversation_context else 0
        )
        
        # Check for explicit confirmation patterns first
        for pattern in cls.CONFIRMATION_PATTERNS:
            if re.search(pattern, input_lower, re.IGNORECASE):
                logger.info(
                    "Detected deployment execution request via pattern match",
                    user_input=user_input[:100],
                    matched_pattern=pattern
                )
                return DeploymentPhase.EXECUTE
        
        # Check conversation context for recent preview
        has_recent_preview = conversation_context and cls._has_recent_preview(conversation_context)
        logger.info(
            "Conversation context analysis",
            has_recent_preview=has_recent_preview,
            input_contains_proceed="proceed" in input_lower,
            input_contains_deploy="deploy" in input_lower,
            input_contains_confirm="confirm" in input_lower,
            input_contains_yes="yes" in input_lower
        )
        
        if has_recent_preview:
            # If there's a recent preview and user is asking to deploy, it's execution
            if any(keyword in input_lower for keyword in ["deploy", "proceed", "confirm", "yes"]):
                logger.info(
                    "Detected deployment execution after recent preview",
                    user_input=user_input[:100]
                )
                return DeploymentPhase.EXECUTE
        
        logger.info(
            "Detected deployment preview request (fallback)",
            user_input=user_input[:100]
        )
        return DeploymentPhase.PREVIEW
    
    @classmethod
    def _has_recent_preview(cls, conversation_context: list[dict]) -> bool:
        """Check if there's a recent deployment preview in conversation context."""
        logger.info(
            "Analyzing conversation context for recent preview",
            total_messages=len(conversation_context),
            last_5_messages_count=len(conversation_context[-5:])
        )
        
        for i, message in enumerate(conversation_context[-5:]):
            content = message.get("content", "").lower()
            has_next_step = "next step: reply with" in content
            has_proceed = "proceed" in content
            has_deployment = "deployment" in content
            has_preview = "preview" in content
            
            logger.info(
                f"Checking message {i+1}/5 for preview indicators",
                has_next_step=has_next_step,
                has_proceed=has_proceed,
                has_deployment=has_deployment,
                has_preview=has_preview,
                content_preview=content[:200] if content else ""
            )
            
            if (has_next_step and has_proceed) or (has_deployment and has_preview):
                logger.info("Found recent deployment preview in conversation context")
                return True
        
        logger.info("No recent deployment preview found in conversation context")
        return False


class DeploymentStateManager:
    """Manages deployment state storage and retrieval."""
    
    def __init__(self):
        self._states: dict[str, DeploymentState] = {}
    
    def store_preview_state(self, state: DeploymentState) -> None:
        """Store deployment preview state for later execution."""
        self._states[state.deployment_id] = state
        logger.info(
            "Stored deployment preview state",
            deployment_id=state.deployment_id,
            user_id=state.user_id,
            expires_at=state.expires_at.isoformat()
        )
    
    def get_preview_state(self, deployment_id: str) -> DeploymentState | None:
        """Retrieve deployment preview state by ID."""
        state = self._states.get(deployment_id)
        if not state:
            logger.warning("Deployment state not found", deployment_id=deployment_id)
            return None
            
        if state.is_expired():
            logger.warning("Deployment state expired", deployment_id=deployment_id)
            del self._states[deployment_id]
            return None
            
        return state
    
    def find_latest_state_for_user(self, user_id: str) -> DeploymentState | None:
        """Find the most recent deployment state for a user."""
        user_states = [
            state for state in self._states.values()
            if state.user_id == user_id and not state.is_expired()
        ]
        
        if not user_states:
            return None
            
        # Return the most recently created state
        return max(user_states, key=lambda s: s.created_at)
    
    def cleanup_expired_states(self) -> int:
        """Remove expired deployment states."""
        expired_ids = [
            deployment_id for deployment_id, state in self._states.items()
            if state.is_expired()
        ]
        
        for deployment_id in expired_ids:
            del self._states[deployment_id]
            
        if expired_ids:
            logger.info("Cleaned up expired deployment states", count=len(expired_ids))
            
        return len(expired_ids)
    
    def clear_user_states(self, user_id: str) -> int:
        """Clear all states for a specific user."""
        user_state_ids = [
            deployment_id for deployment_id, state in self._states.items()
            if state.user_id == user_id
        ]
        
        for deployment_id in user_state_ids:
            del self._states[deployment_id]
            
        logger.info("Cleared user deployment states", user_id=user_id, count=len(user_state_ids))
        return len(user_state_ids)


# Global instance for deployment state management
deployment_state_manager = DeploymentStateManager()