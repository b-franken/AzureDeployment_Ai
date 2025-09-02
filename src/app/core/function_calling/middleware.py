from __future__ import annotations

from collections.abc import Callable
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer(__name__)


class ValidationResult:
    def __init__(
        self,
        is_valid: bool,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ):
        self.is_valid = is_valid
        self.errors = errors or []
        self.warnings = warnings or []


class ValidationMiddleware:
    def __init__(self) -> None:
        self._pre_validators: list[Callable[[dict[str, Any]], ValidationResult]] = []
        self._post_validators: list[Callable[[Any], ValidationResult]] = []
        self._context_validators: list[Callable[[dict[str, Any]], ValidationResult]] = []

    def add_pre_validator(self, validator: Callable[[dict[str, Any]], ValidationResult]) -> None:
        with tracer.start_as_current_span("add_pre_validator") as span:
            self._pre_validators.append(validator)
            span.set_attributes(
                {
                    "validator.type": "pre",
                    "validator.name": validator.__name__,
                    "total_pre_validators": len(self._pre_validators),
                }
            )
            span.set_status(Status(StatusCode.OK))

    def add_post_validator(self, validator: Callable[[Any], ValidationResult]) -> None:
        with tracer.start_as_current_span("add_post_validator") as span:
            self._post_validators.append(validator)
            span.set_attributes(
                {
                    "validator.type": "post",
                    "validator.name": validator.__name__,
                    "total_post_validators": len(self._post_validators),
                }
            )
            span.set_status(Status(StatusCode.OK))

    def add_context_validator(
        self, validator: Callable[[dict[str, Any]], ValidationResult]
    ) -> None:
        with tracer.start_as_current_span("add_context_validator") as span:
            self._context_validators.append(validator)
            span.set_attributes(
                {
                    "validator.type": "context",
                    "validator.name": validator.__name__,
                    "total_context_validators": len(self._context_validators),
                }
            )
            span.set_status(Status(StatusCode.OK))

    async def validate_input(
        self, arguments: dict[str, Any], function_name: str
    ) -> ValidationResult:
        with tracer.start_as_current_span("middleware_input_validation") as span:
            span.set_attributes(
                {
                    "function.name": function_name,
                    "validation.pre_validators": len(self._pre_validators),
                    "validation.argument_count": len(arguments),
                }
            )

            all_errors = []
            all_warnings = []

            for validator in self._pre_validators:
                try:
                    result = validator(arguments)
                    all_errors.extend(result.errors)
                    all_warnings.extend(result.warnings)

                    if not result.is_valid:
                        span.add_event(
                            "pre_validation_failed",
                            {"validator": validator.__name__, "errors": result.errors},
                        )
                except Exception as e:
                    error_msg = f"Pre-validator {validator.__name__} failed: {str(e)}"
                    all_errors.append(error_msg)
                    span.record_exception(e)

            is_valid = len(all_errors) == 0
            result = ValidationResult(is_valid, all_errors, all_warnings)

            span.set_attributes(
                {
                    "validation.success": is_valid,
                    "validation.error_count": len(all_errors),
                    "validation.warning_count": len(all_warnings),
                }
            )

            if not is_valid:
                span.set_status(
                    Status(
                        StatusCode.ERROR,
                        f"Input validation failed with {len(all_errors)} errors",
                    )
                )
            else:
                span.set_status(Status(StatusCode.OK))

            return result

    async def validate_output(self, result: Any, function_name: str) -> ValidationResult:
        with tracer.start_as_current_span("middleware_output_validation") as span:
            span.set_attributes(
                {
                    "function.name": function_name,
                    "validation.post_validators": len(self._post_validators),
                    "result.type": type(result).__name__,
                }
            )

            all_errors = []
            all_warnings = []

            for validator in self._post_validators:
                try:
                    validation_result = validator(result)
                    all_errors.extend(validation_result.errors)
                    all_warnings.extend(validation_result.warnings)

                    if not validation_result.is_valid:
                        span.add_event(
                            "post_validation_failed",
                            {"validator": validator.__name__, "errors": validation_result.errors},
                        )
                except Exception as e:
                    error_msg = f"Post-validator {validator.__name__} failed: {str(e)}"
                    all_errors.append(error_msg)
                    span.record_exception(e)

            is_valid = len(all_errors) == 0
            validation_result = ValidationResult(is_valid, all_errors, all_warnings)

            span.set_attributes(
                {
                    "validation.success": is_valid,
                    "validation.error_count": len(all_errors),
                    "validation.warning_count": len(all_warnings),
                }
            )

            if not is_valid:
                span.set_status(
                    Status(
                        StatusCode.ERROR, f"Output validation failed with {len(all_errors)} errors"
                    )
                )
            else:
                span.set_status(Status(StatusCode.OK))

            return validation_result

    async def validate_context(
        self, context: dict[str, Any], function_name: str
    ) -> ValidationResult:
        with tracer.start_as_current_span("middleware_context_validation") as span:
            span.set_attributes(
                {
                    "function.name": function_name,
                    "validation.context_validators": len(self._context_validators),
                    "context.keys": list(context.keys()),
                }
            )

            all_errors = []
            all_warnings = []

            for validator in self._context_validators:
                try:
                    validation_result = validator(context)
                    all_errors.extend(validation_result.errors)
                    all_warnings.extend(validation_result.warnings)

                    if not validation_result.is_valid:
                        span.add_event(
                            "context_validation_failed",
                            {"validator": validator.__name__, "errors": validation_result.errors},
                        )
                except Exception as e:
                    error_msg = f"Context validator {validator.__name__} failed: {str(e)}"
                    all_errors.append(error_msg)
                    span.record_exception(e)

            is_valid = len(all_errors) == 0
            validation_result = ValidationResult(is_valid, all_errors, all_warnings)

            span.set_attributes(
                {
                    "validation.success": is_valid,
                    "validation.error_count": len(all_errors),
                    "validation.warning_count": len(all_warnings),
                }
            )

            if not is_valid:
                span.set_status(
                    Status(
                        StatusCode.ERROR, f"Context validation failed with {len(all_errors)} errors"
                    )
                )
            else:
                span.set_status(Status(StatusCode.OK))

            return validation_result


def create_azure_context_validator() -> Callable[[dict[str, Any]], ValidationResult]:
    def validate_azure_context(context: dict[str, Any]) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        required_fields = ["subscription_id"]
        recommended_fields = ["resource_group", "location"]

        for field in required_fields:
            if field not in context:
                errors.append(f"Required Azure context field missing: {field}")

        for field in recommended_fields:
            if field not in context:
                warnings.append(f"Recommended Azure context field missing: {field}")

        if "subscription_id" in context:
            sub_id = context["subscription_id"]
            if not isinstance(sub_id, str) or len(sub_id) != 36:
                errors.append("Invalid Azure subscription_id format")

        return ValidationResult(len(errors) == 0, errors, warnings)

    return validate_azure_context


def create_cost_limit_validator(max_cost: float) -> Callable[[dict[str, Any]], ValidationResult]:
    def validate_cost_limit(arguments: dict[str, Any]) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        if "estimated_cost" in arguments:
            cost = arguments["estimated_cost"]
            if isinstance(cost, int | float) and cost > max_cost:
                errors.append(f"Estimated cost ${cost} exceeds limit ${max_cost}")

        return ValidationResult(len(errors) == 0, errors, warnings)

    return validate_cost_limit
