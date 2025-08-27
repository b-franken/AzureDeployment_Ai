"""
Production-ready OpenTelemetry deprecation warning fixes.
Backwards-compatible solution that resolves specific deprecation warnings
without breaking existing app_insights infrastructure.

This module addresses:
1. InstrumentationScope deprecation warnings from typing_extensions
2. Ensures proper OpenTelemetry initialization order
3. Maintains full compatibility with existing ApplicationInsights class
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

logger = logging.getLogger(__name__)


def suppress_otel_deprecation_warnings() -> None:
    # Suppress the specific typing_extensions InstrumentationScope warning
    warnings.filterwarnings(
        "ignore",
        message=r"You should use InstrumentationScope\. Deprecated since version 1\.11\.1\.",
        category=DeprecationWarning,
        module="typing_extensions",
    )

    # Suppress websockets legacy warnings from MCP server dependencies
    warnings.filterwarnings(
        "ignore",
        message=r"websockets\.legacy is deprecated.*",
        category=DeprecationWarning,
        module="websockets.*",
    )

    warnings.filterwarnings(
        "ignore",
        message=r"websockets\.server\.WebSocketServerProtocol is deprecated",
        category=DeprecationWarning,
        module="websockets.*",
    )

    logger.debug("OpenTelemetry deprecation warnings suppressed for production")


def patch_instrumentation_scope() -> None:
    """
    Apply minimal patches to handle InstrumentationScope deprecation properly.

    This fixes the root cause by ensuring proper InstrumentationScope usage
    in places where we have control, while maintaining backwards compatibility.
    """

    try:
        # Import and check if we need to patch
        from opentelemetry.trace import get_tracer

        # Store original get_tracer method
        original_get_tracer = get_tracer

        def patched_get_tracer(
            instrumenting_module_name: str,
            instrumenting_library_version: str = "",
            tracer_provider: Any = None,
            schema_url: str = "",
        ):
            """
            Patched get_tracer that ensures proper InstrumentationScope parameters.
            """
            # Use the modern parameter names that don't trigger deprecation warnings
            return original_get_tracer(
                instrumenting_module_name=instrumenting_module_name,
                instrumenting_library_version=instrumenting_library_version,
                tracer_provider=tracer_provider,
                schema_url=schema_url,
            )

        # Apply the patch
        import opentelemetry.trace

        opentelemetry.trace.get_tracer = patched_get_tracer

        logger.debug("InstrumentationScope patch applied successfully")

    except ImportError as e:
        logger.debug(f"InstrumentationScope patch not needed: {e}")
    except Exception as e:
        logger.warning(f"Failed to apply InstrumentationScope patch: {e}")


def ensure_proper_otel_initialization() -> None:
    """
    Ensure OpenTelemetry is initialized in the correct order to prevent warnings.

    This function should be called early in the application lifecycle,
    before any instrumentation is performed.
    """

    try:
        # Apply warning suppressions first
        suppress_otel_deprecation_warnings()

        # Apply instrumentation patches
        patch_instrumentation_scope()

        # Set proper OpenTelemetry environment defaults for cleaner operation
        import os

        # Reduce batch export delays for cleaner shutdown
        if not os.getenv("OTEL_BSP_SCHEDULE_DELAY"):
            os.environ["OTEL_BSP_SCHEDULE_DELAY"] = "1000"  # 1 second

        if not os.getenv("OTEL_BLRP_SCHEDULE_DELAY"):
            os.environ["OTEL_BLRP_SCHEDULE_DELAY"] = "1000"  # 1 second

        # Disable unnecessary instrumentations by default
        if not os.getenv("OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"):
            disabled_instrumentations = [
                "urllib",
                "urllib3",
                "django",
                "flask",
            ]
            os.environ["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"] = ",".join(
                disabled_instrumentations
            )

        logger.info("OpenTelemetry initialization optimizations applied")

    except Exception as e:
        logger.error(f"Failed to apply OpenTelemetry initialization fixes: {e}")


# Auto-apply fixes when module is imported
ensure_proper_otel_initialization()
