from __future__ import annotations

from typing import Any, ClassVar
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import field_validator, model_validator

tracer = trace.get_tracer(__name__)


class ValidationMixin:
    _validation_rules: ClassVar[dict[str, Any]] = {}
    _custom_validators: ClassVar[dict[str, callable]] = {}
    
    @model_validator(mode="after")
    def run_custom_validation(self) -> "ValidationMixin":
        with tracer.start_as_current_span("schema_custom_validation") as span:
            span.set_attributes({
                "schema.name": self.__class__.__name__,
                "validation.custom_validators": len(self._custom_validators)
            })
            
            validation_results = []
            
            for field_name, validator_func in self._custom_validators.items():
                try:
                    field_value = getattr(self, field_name, None)
                    if field_value is not None:
                        validator_func(field_value)
                        validation_results.append(f"{field_name}:passed")
                except Exception as e:
                    validation_results.append(f"{field_name}:failed")
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise
            
            span.set_attributes({
                "validation.results": validation_results,
                "validation.success": True
            })
            span.set_status(Status(StatusCode.OK))
            return self
    
    @classmethod
    def add_validation_rule(cls, field_name: str, validator_func: callable) -> None:
        with tracer.start_as_current_span("schema_add_validation_rule") as span:
            cls._custom_validators[field_name] = validator_func
            span.set_attributes({
                "schema.name": cls.__name__,
                "validation.field": field_name,
                "validation.function": validator_func.__name__
            })
            span.set_status(Status(StatusCode.OK))
    
    def validate_business_rules(self) -> list[str]:
        with tracer.start_as_current_span("schema_business_validation") as span:
            span.set_attributes({
                "schema.name": self.__class__.__name__,
                "business_rules.count": len(self._validation_rules)
            })
            
            violations = []
            for rule_name, rule_func in self._validation_rules.items():
                try:
                    if not rule_func(self):
                        violation = f"Business rule violated: {rule_name}"
                        violations.append(violation)
                        span.add_event("business_rule_violation", {"rule": rule_name})
                except Exception as e:
                    error_msg = f"Business rule error: {rule_name} - {e}"
                    violations.append(error_msg)
                    span.record_exception(e)
            
            span.set_attributes({
                "business_rules.violations": len(violations),
                "business_rules.success": len(violations) == 0
            })
            
            if violations:
                span.set_status(Status(StatusCode.ERROR, f"{len(violations)} business rule violations"))
            else:
                span.set_status(Status(StatusCode.OK))
            
            return violations
    
    @classmethod
    def register_business_rule(cls, rule_name: str, rule_func: callable) -> None:
        with tracer.start_as_current_span("schema_register_business_rule") as span:
            cls._validation_rules[rule_name] = rule_func
            span.set_attributes({
                "schema.name": cls.__name__,
                "business_rule.name": rule_name,
                "business_rule.function": rule_func.__name__
            })
            span.set_status(Status(StatusCode.OK))