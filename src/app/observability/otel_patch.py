"""
OpenTelemetry patch to fix _FixedFindCallerLogger attribute validation errors.
This module patches the OpenTelemetry attribute validation to properly handle logger objects.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

def patch_opentelemetry_attributes() -> None:
    """
    Patch OpenTelemetry attribute validation to prevent logger object warnings.
    
    This prevents the "_FixedFindCallerLogger" validation errors by making
    OpenTelemetry reject logger objects before they cause warnings.
    """
    try:
        # Patch multiple locations where attributes are validated
        modules_to_patch = [
            'opentelemetry.util.attributes',
            'opentelemetry.attributes',
            'opentelemetry.sdk.util.attributes'
        ]
        
        for module_name in modules_to_patch:
            try:
                import importlib
                module = importlib.import_module(module_name)
                
                original_is_valid = getattr(module, 'is_valid_attribute_value', None)
                if original_is_valid is None:
                    continue
                    
                def create_patched_validator(orig_func):
                    def patched_is_valid_attribute_value(value: Any) -> bool:
                        # Reject any logger objects immediately
                        if hasattr(value, '__class__'):
                            class_name = value.__class__.__name__
                            if 'Logger' in class_name or 'FindCaller' in class_name:
                                return False
                                
                        # Check for private attributes that shouldn't be included
                        if isinstance(value, dict):
                            for key in value.keys():
                                if isinstance(key, str) and key.startswith('_'):
                                    return False
                                    
                        return orig_func(value)
                    return patched_is_valid_attribute_value
                
                # Replace the validation function
                setattr(module, 'is_valid_attribute_value', create_patched_validator(original_is_valid))
                logger.info(f"Patched {module_name} attribute validation")
                
            except ImportError:
                continue
            except Exception as e:
                logger.debug(f"Could not patch {module_name}: {e}")
        
        # Also try to patch the direct validation calls
        try:
            import opentelemetry.attributes as otel_attrs
            if hasattr(otel_attrs, '_is_valid_attribute_value'):
                original = otel_attrs._is_valid_attribute_value
                def patched_private_validator(value: Any) -> bool:
                    if hasattr(value, '__class__'):
                        class_name = value.__class__.__name__
                        if 'Logger' in class_name or 'FindCaller' in class_name:
                            return False
                    return original(value)
                otel_attrs._is_valid_attribute_value = patched_private_validator
                logger.info("Patched private attribute validator")
        except Exception as e:
            logger.debug(f"Could not patch private validator: {e}")
        
    except Exception as e:
        logger.warning(f"Failed to patch OpenTelemetry attributes: {e}")


def patch_logging_handlers() -> None:
    """
    Patch logging handlers to prevent logger objects from reaching OpenTelemetry.
    """
    try:
        import opentelemetry.instrumentation.logging
        
        # Get the OpenTelemetry logging handler if it exists
        root_logger = logging.getLogger()
        
        for handler in root_logger.handlers:
            if 'opentelemetry' in handler.__class__.__module__.lower():
                original_emit = handler.emit
                
                def safe_emit(record):
                    # Clean the record before emitting
                    if hasattr(record, '__dict__'):
                        # Remove problematic attributes
                        clean_dict = {}
                        for key, value in record.__dict__.items():
                            if key.startswith('_'):
                                continue
                            if hasattr(value, '__class__') and 'Logger' in value.__class__.__name__:
                                continue
                            clean_dict[key] = value
                        record.__dict__ = clean_dict
                    
                    return original_emit(record)
                
                handler.emit = safe_emit
                
        logger.info("OpenTelemetry logging handlers patched")
        
    except Exception as e:
        logger.debug(f"Could not patch logging handlers: {e}")


def apply_all_patches() -> None:
    """Apply all OpenTelemetry patches to prevent attribute validation errors."""
    patch_opentelemetry_attributes()
    patch_logging_handlers()