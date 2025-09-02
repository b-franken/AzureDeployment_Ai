from __future__ import annotations

import logging
from app.core.logging import get_logger

logger = get_logger(__name__)

__all__: list[str] = []

try:
    from .tool import AzureProvision  # noqa: F401

    __all__.append("AzureProvision")
except ImportError:
    logger.exception("Failed to import AzureProvision")
except Exception as e:
    logger.error(f"Unexpected error importing AzureProvision: {e}")
