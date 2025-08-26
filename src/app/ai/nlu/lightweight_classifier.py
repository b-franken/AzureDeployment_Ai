"""Ultra-lightweight classification without any ML dependencies."""
from __future__ import annotations

import re
from typing import Any
import logging

logger = logging.getLogger(__name__)


class LightweightIntentClassifier:
    """
    Simple rule-based classifier that doesn't require any ML libraries.
    Perfect for development environments and Docker size optimization.
    """
    
    def __init__(self) -> None:
        # Common deployment/provisioning keywords
        self.provision_keywords = [
            'create', 'deploy', 'provision', 'setup', 'make', 'build', 'add',
            'new', 'launch', 'start', 'initialize', 'configure'
        ]
        
        # Resource type patterns
        self.resource_patterns = {
            'storage': [
                r'\bstorage\b', r'\bblob\b', r'\bs3\b', r'\bbucket\b'
            ],
            'webapp': [
                r'\bweb\s*app\b', r'\bapp\s*service\b', r'\bwebsite\b', r'\bapi\b'
            ],
            'vm': [
                r'\bvm\b', r'\bvirtual\s*machine\b', r'\bcompute\b', r'\bserver\b', r'\binstance\b'
            ],
            'database': [
                r'\bdatabase\b', r'\bdb\b', r'\bsql\b', r'\bmysql\b', r'\bpostgres\b'
            ],
            'network': [
                r'\bnetwork\b', r'\bvnet\b', r'\bvpc\b', r'\bsubnet\b'
            ],
            'kubernetes': [
                r'\baks\b', r'\bkubernetes\b', r'\bk8s\b', r'\bcluster\b'
            ],
            'resource_group': [
                r'\bresource\s*group\b', r'\brg\b'
            ]
        }
        
        # Location patterns
        self.location_patterns = [
            r'\bwest\s*europe\b', r'\beast\s*us\b', r'\buk\s*south\b',
            r'\bnorth\s*europe\b', r'\bcentral\s*us\b', r'\bsouth\s*east\s*asia\b'
        ]
        
        # Compile patterns for performance
        self._compiled_patterns = {
            resource_type: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            for resource_type, patterns in self.resource_patterns.items()
        }
        
    def predict_proba(self, texts: list[str]) -> list[list[float]]:
        """
        Mock the scikit-learn interface for compatibility.
        Returns probabilities for [not_provision, provision].
        """
        results = []
        for text in texts:
            is_provision = self._is_provision_intent(text)
            if is_provision:
                # High confidence for provision intent
                prob = [0.2, 0.8]  
            else:
                # Low confidence or other intent
                prob = [0.8, 0.2]
            results.append(prob)
        return results
    
    def _is_provision_intent(self, text: str) -> bool:
        """Determine if text expresses provisioning intent."""
        text_lower = text.lower()
        
        # Check for provision keywords
        has_provision_keyword = any(
            keyword in text_lower for keyword in self.provision_keywords
        )
        
        # Check for resource type mentions
        has_resource_type = any(
            any(pattern.search(text) for pattern in patterns)
            for patterns in self._compiled_patterns.values()
        )
        
        # Simple heuristic: need both intent and resource
        return has_provision_keyword and has_resource_type
    
    def get_resource_type(self, text: str) -> str | None:
        """Extract the primary resource type from text."""
        for resource_type, patterns in self._compiled_patterns.items():
            if any(pattern.search(text) for pattern in patterns):
                return resource_type
        return None
    
    def get_confidence(self, text: str) -> float:
        """Get confidence score for the classification."""
        if self._is_provision_intent(text):
            # Higher confidence if we can identify specific resource type
            resource_type = self.get_resource_type(text)
            return 0.8 if resource_type else 0.6
        return 0.3


# Global instance for reuse
_lightweight_classifier: LightweightIntentClassifier | None = None

def get_lightweight_classifier() -> LightweightIntentClassifier:
    """Get global lightweight classifier instance."""
    global _lightweight_classifier
    if _lightweight_classifier is None:
        _lightweight_classifier = LightweightIntentClassifier()
    return _lightweight_classifier


def replace_embeddings_classifier_in_dev() -> bool:
    """
    Check if we should use lightweight classifier instead of embeddings.
    Returns True if in development mode.
    """
    import os
    environment = os.getenv('ENVIRONMENT', 'development')
    use_lightweight = os.getenv('USE_LIGHTWEIGHT_CLASSIFIER', 'true').lower() in {'1', 'true', 'yes'}
    
    return environment == 'development' and use_lightweight