import logging
from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


def patch_opentelemetry_attributes() -> None:
    """
    Patch OpenTelemetry attribute validation to prevent logger object warnings.

    This prevents the "_FixedFindCallerLogger" validation errors by making
    OpenTelemetry reject logger objects before they cause warnings.
    """
    try:
        try:
            import opentelemetry.attributes as otel_attrs

            if hasattr(otel_attrs, "_clean_attribute_value"):
                original_clean = otel_attrs._clean_attribute_value

                def patched_clean_attribute_value(value: Any, limit: int | None) -> Any:
                    if is_logger_object(value):
                        return f"<{value.__class__.__name__}>"
                    return original_clean(value, limit)

                otel_attrs._clean_attribute_value = patched_clean_attribute_value
                logger.info("Patched _clean_attribute_value")

            if hasattr(otel_attrs, "_clean_extended_attribute_value"):
                original_extended_clean = otel_attrs._clean_extended_attribute_value

                def patched_clean_extended_attribute_value(
                    value: Any, max_len: int | None = None
                ) -> Any:
                    if is_logger_object(value):
                        return f"<{value.__class__.__name__}>"
                    return original_extended_clean(value, max_len)

                otel_attrs._clean_extended_attribute_value = patched_clean_extended_attribute_value
                logger.info("Patched _clean_extended_attribute_value")

        except Exception as e:
            logger.debug(f"Could not patch opentelemetry.attributes cleaning functions: {e}")

        modules_to_patch = [
            "opentelemetry.util.attributes",
            "opentelemetry.sdk.util.attributes",
            "opentelemetry.sdk.trace.attributes",
            "opentelemetry.trace.attributes",
        ]

        def is_logger_object(value: Any) -> bool:
            """Check if a value is a logger object that should be filtered."""
            if not hasattr(value, "__class__"):
                return False

            class_name = value.__class__.__name__
            module_name = getattr(value.__class__, "__module__", "")

            logger_patterns = [
                "Logger",
                "FindCaller",
                "BoundLogger",
                "FilteringBoundLogger",
                "_FixedFindCallerLogger",
                "StreamLogger",
                "FileLogger",
                "RotatingFileLogger",
                "TimedRotatingFileLogger",
            ]

            return (
                any(pattern in class_name for pattern in logger_patterns)
                or "logging" in module_name.lower()
                or "structlog" in module_name.lower()
            )

        for module_name in modules_to_patch:
            try:
                import importlib

                module = importlib.import_module(module_name)

                original_is_valid = getattr(module, "is_valid_attribute_value", None)
                if original_is_valid is None:
                    continue

                def create_patched_validator(
                    orig_func: Callable[[Any], bool],
                ) -> Callable[[Any], bool]:
                    def patched_is_valid_attribute_value(value: Any) -> bool:
                        if is_logger_object(value):
                            return False

                        if isinstance(value, dict):
                            for key, val in value.items():
                                if isinstance(key, str) and key.startswith("_"):
                                    return False
                                if is_logger_object(val):
                                    return False

                        if isinstance(value, list | tuple) and not isinstance(value, str | bytes):
                            for item in value:
                                if is_logger_object(item):
                                    return False

                        try:
                            return orig_func(value)
                        except Exception:
                            return False

                    return patched_is_valid_attribute_value

                setattr(  # noqa: B010
                    module, "is_valid_attribute_value", create_patched_validator(original_is_valid)
                )
                logger.info(f"Patched {module_name} attribute validation")

            except ImportError:
                continue
            except Exception as e:
                logger.debug(f"Could not patch {module_name}: {e}")

        try:
            import opentelemetry.attributes as otel_attrs

            if hasattr(otel_attrs, "_is_valid_attribute_value"):
                original = otel_attrs._is_valid_attribute_value

                def patched_private_validator(value: Any) -> bool:
                    if is_logger_object(value):
                        return False
                    try:
                        result = original(value)
                        return bool(result)
                    except Exception:
                        return False

                otel_attrs._is_valid_attribute_value = patched_private_validator
                logger.info("Patched private attribute validator")
        except Exception as e:
            logger.debug(f"Could not patch private validator: {e}")

        try:
            import warnings

            original_warn = warnings.warn

            def filtered_warn(
                message: str | Warning,
                category: type[Warning] | None = None,
                stacklevel: int = 1,
                source: Any = None,
            ) -> None:
                if isinstance(message, str) and "_FixedFindCallerLogger" in message:
                    return None
                return original_warn(message, category, stacklevel, source)

            warnings.warn = filtered_warn  # type: ignore[assignment]
            logger.info("Patched warnings.warn to suppress _FixedFindCallerLogger warnings")
        except Exception as e:
            logger.debug(f"Could not patch warnings: {e}")

    except Exception as e:
        logger.warning(f"Failed to patch OpenTelemetry attributes: {e}")


def patch_logging_handlers() -> None:
    """
    Patch logging handlers to prevent logger objects from reaching OpenTelemetry.
    """
    try:
        root_logger = logging.getLogger()

        def is_logger_object(value: Any) -> bool:
            """Check if a value is a logger object that should be filtered."""
            if not hasattr(value, "__class__"):
                return False

            class_name = value.__class__.__name__
            module_name = getattr(value.__class__, "__module__", "")

            logger_patterns = [
                "Logger",
                "FindCaller",
                "BoundLogger",
                "FilteringBoundLogger",
                "_FixedFindCallerLogger",
                "StreamLogger",
                "FileLogger",
                "RotatingFileLogger",
                "TimedRotatingFileLogger",
            ]

            return (
                any(pattern in class_name for pattern in logger_patterns)
                or "logging" in module_name.lower()
                or "structlog" in module_name.lower()
            )

        def clean_value(value: Any) -> Any:
            """Recursively clean a value of logger objects."""
            if is_logger_object(value):
                return f"<{value.__class__.__name__}>"

            if isinstance(value, dict):
                return {
                    k: clean_value(v)
                    for k, v in value.items()
                    if not str(k).startswith("_") and not is_logger_object(v)
                }

            if isinstance(value, list | tuple) and not isinstance(value, str | bytes):
                cleaned = [clean_value(item) for item in value if not is_logger_object(item)]
                return type(value)(cleaned) if cleaned else []

            return value

        for handler in root_logger.handlers:
            if (
                "opentelemetry" in handler.__class__.__module__.lower()
                or "azure.monitor" in handler.__class__.__module__.lower()
            ):
                original_emit = getattr(handler, "_original_emit", None) or handler.emit

                def create_safe_emit(orig_emit: Callable[[Any], None]) -> Callable[[Any], None]:
                    def safe_emit(record: Any) -> None:
                        if hasattr(record, "__dict__"):
                            clean_dict = {}
                            for key, value in record.__dict__.items():
                                if key.startswith("_"):
                                    continue

                                cleaned_value = clean_value(value)
                                if cleaned_value is not None:
                                    clean_dict[key] = cleaned_value

                            original_dict = record.__dict__.copy()
                            record.__dict__.clear()
                            record.__dict__.update(clean_dict)

                        try:
                            return orig_emit(record)
                        finally:
                            if hasattr(record, "__dict__") and "original_dict" in locals():
                                record.__dict__.clear()
                                record.__dict__.update(original_dict)

                    return safe_emit

                handler._original_emit = original_emit  # type: ignore[attr-defined]
                handler.emit = create_safe_emit(original_emit)  # type: ignore[assignment]

        logger.info("OpenTelemetry logging handlers patched")

    except Exception as e:
        logger.debug(f"Could not patch logging handlers: {e}")


def apply_all_patches() -> None:
    """Apply all OpenTelemetry patches to prevent attribute validation errors."""
    patch_opentelemetry_attributes()
    patch_logging_handlers()
