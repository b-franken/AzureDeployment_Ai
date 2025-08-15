from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__: list[str] = []

try:
    from .tool import AzureProvision  # noqa: F401

    __all__.append("AzureProvision")
except ImportError:
    logger.exception("Failed to import AzureProvision")
except Exception as e:
    logger.error(f"Unexpected error importing AzureProvision: {e}")
