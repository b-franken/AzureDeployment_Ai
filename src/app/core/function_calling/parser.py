from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, ValidationError

from app.core.schemas.base import BaseSchema

tracer = trace.get_tracer(__name__)

T = TypeVar("T", bound=BaseModel)


class ParseRequest(BaseSchema):
    content: str
    target_schema: str
    format_hint: str = "json"
    strict_mode: bool = True
    fallback_enabled: bool = True


class ParseResponse(BaseSchema):
    success: bool
    parsed_data: dict[str, Any] | None = None
    schema_name: str
    confidence: float = 0.0
    warnings: list[str] = []
    error_message: str | None = None
    parsing_method: str = "unknown"


class StructuredOutputParser:
    def __init__(self) -> None:
        self._schema_cache: dict[str, type[BaseModel]] = {}
        self._parsing_strategies = [
            self._parse_json_direct,
            self._parse_json_from_code_block,
            self._parse_json_from_text,
            self._parse_key_value_pairs,
        ]

    def register_schema(self, schema_cls: type[T]) -> None:
        with tracer.start_as_current_span("parser_register_schema") as span:
            schema_name = schema_cls.__name__
            self._schema_cache[schema_name] = schema_cls

            span.set_attributes(
                {
                    "schema.name": schema_name,
                    "schema.module": schema_cls.__module__,
                    "parser.total_schemas": len(self._schema_cache),
                }
            )
            span.set_status(Status(StatusCode.OK))

    async def parse(self, request: ParseRequest) -> ParseResponse:
        with tracer.start_as_current_span("structured_output_parsing") as span:
            span.set_attributes(
                {
                    "parser.target_schema": request.target_schema,
                    "parser.content_length": len(request.content),
                    "parser.format_hint": request.format_hint,
                    "parser.strict_mode": request.strict_mode,
                    "parser.fallback_enabled": request.fallback_enabled,
                }
            )

            target_schema = self._schema_cache.get(request.target_schema)
            if not target_schema:
                error_msg = f"Schema {request.target_schema} not registered"
                span.set_status(Status(StatusCode.ERROR, error_msg))
                return ParseResponse(
                    correlation_id=request.correlation_id,
                    success=False,
                    schema_name=request.target_schema,
                    error_message=error_msg,
                )

            best_result = None
            highest_confidence = 0.0
            parsing_attempts = []

            for strategy in self._parsing_strategies:
                try:
                    parsed_data = await strategy(request.content, span)
                    if parsed_data is None:
                        continue

                    validation_result = await self._validate_against_schema(
                        parsed_data, target_schema, span
                    )

                    if validation_result["success"]:
                        confidence = self._calculate_confidence(
                            parsed_data, target_schema, strategy.__name__
                        )

                        parsing_attempts.append(
                            {"method": strategy.__name__, "confidence": confidence, "success": True}
                        )

                        if confidence > highest_confidence:
                            highest_confidence = confidence
                            best_result = {
                                "data": validation_result["validated_data"],
                                "method": strategy.__name__,
                                "confidence": confidence,
                                "warnings": validation_result.get("warnings", []),
                            }

                        if request.strict_mode and confidence >= 0.9:
                            break

                except Exception as e:
                    parsing_attempts.append(
                        {"method": strategy.__name__, "success": False, "error": str(e)}
                    )
                    span.add_event(
                        "parsing_strategy_failed", {"strategy": strategy.__name__, "error": str(e)}
                    )

            span.set_attributes(
                {
                    "parser.attempts": len(parsing_attempts),
                    "parser.successful_attempts": len(
                        [a for a in parsing_attempts if a.get("success", False)]
                    ),
                    "parser.best_confidence": highest_confidence,
                }
            )

            if best_result:
                span.set_status(Status(StatusCode.OK))
                return ParseResponse(
                    correlation_id=request.correlation_id,
                    success=True,
                    parsed_data=best_result["data"],
                    schema_name=request.target_schema,
                    confidence=best_result["confidence"],
                    warnings=best_result["warnings"],
                    parsing_method=best_result["method"],
                )
            else:
                error_msg = f"Failed to parse content into {request.target_schema}"
                span.set_status(Status(StatusCode.ERROR, error_msg))
                return ParseResponse(
                    correlation_id=request.correlation_id,
                    success=False,
                    schema_name=request.target_schema,
                    error_message=error_msg,
                    confidence=0.0,
                )

    async def _parse_json_direct(self, content: str, span: trace.Span) -> dict[str, Any] | None:
        with tracer.start_as_current_span(
            "parse_json_direct", context=trace.set_span_in_context(span)
        ):
            try:
                result = json.loads(content.strip())
                return result if isinstance(result, dict) else None
            except json.JSONDecodeError:
                return None

    async def _parse_json_from_code_block(
        self, content: str, span: trace.Span
    ) -> dict[str, Any] | None:
        with tracer.start_as_current_span(
            "parse_json_code_block", context=trace.set_span_in_context(span)
        ):
            patterns = [r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```", r"`([^`]+)`"]

            for pattern in patterns:
                matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    try:
                        result = json.loads(match.strip())
                        return result if isinstance(result, dict) else None
                    except json.JSONDecodeError:
                        continue
            return None

    async def _parse_json_from_text(self, content: str, span: trace.Span) -> dict[str, Any] | None:
        with tracer.start_as_current_span(
            "parse_json_from_text", context=trace.set_span_in_context(span)
        ):
            json_pattern = r"\{.*?\}"
            matches = re.findall(json_pattern, content, re.DOTALL)

            for match in matches:
                try:
                    parsed = json.loads(match)
                    if isinstance(parsed, dict) and len(parsed) > 0:
                        return parsed
                except json.JSONDecodeError:
                    continue
            return None

    async def _parse_key_value_pairs(self, content: str, span: trace.Span) -> dict[str, Any] | None:
        with tracer.start_as_current_span(
            "parse_key_value_pairs", context=trace.set_span_in_context(span)
        ):
            patterns = [r"(\w+):\s*([^\n,]+)", r"(\w+)\s*=\s*([^\n,]+)", r'"(\w+)":\s*"([^"]+)"']

            result = {}
            for pattern in patterns:
                matches = re.findall(pattern, content)
                for key, value in matches:
                    key = key.strip()
                    value = value.strip().strip("\"'")

                    if value.lower() in ["true", "false"]:
                        result[key] = value.lower() == "true"
                    elif value.isdigit():
                        result[key] = int(value)
                    else:
                        try:
                            result[key] = float(value)
                        except ValueError:
                            result[key] = value

            return result if result else None

    async def _validate_against_schema(
        self, data: dict[str, Any], schema: type[BaseModel], span: trace.Span
    ) -> dict[str, Any]:
        with tracer.start_as_current_span(
            "schema_validation", context=trace.set_span_in_context(span)
        ):
            try:
                validated_instance = schema(**data)
                return {
                    "success": True,
                    "validated_data": validated_instance.model_dump(),
                    "warnings": [],
                }
            except ValidationError as e:
                return {
                    "success": False,
                    "errors": [str(err) for err in e.errors()],
                    "warnings": [],
                }

    def _calculate_confidence(
        self, data: dict[str, Any], schema: type[BaseModel], method_name: str
    ) -> float:
        base_confidence = {
            "_parse_json_direct": 0.95,
            "_parse_json_from_code_block": 0.90,
            "_parse_json_from_text": 0.75,
            "_parse_key_value_pairs": 0.60,
        }.get(method_name, 0.50)

        schema_fields = set(schema.model_fields.keys())
        data_fields = set(data.keys())

        field_coverage = len(data_fields.intersection(schema_fields)) / len(schema_fields)
        extra_fields_penalty = max(0, len(data_fields - schema_fields) * 0.1)

        final_confidence = base_confidence * field_coverage - extra_fields_penalty
        return max(0.0, min(1.0, final_confidence))

    def get_registered_schemas(self) -> dict[str, type[BaseModel]]:
        return self._schema_cache.copy()

    async def batch_parse(self, requests: list[ParseRequest]) -> list[ParseResponse]:
        with tracer.start_as_current_span("batch_parsing") as span:
            span.set_attributes(
                {
                    "batch.size": len(requests),
                    "batch.unique_schemas": len(set(req.target_schema for req in requests)),
                }
            )

            results = []
            for i, request in enumerate(requests):
                result = await self.parse(request)
                results.append(result)

                span.add_event(
                    f"batch_item_{i}_completed",
                    {"success": result.success, "confidence": result.confidence},
                )

            successful_count = len([r for r in results if r.success])
            span.set_attributes(
                {
                    "batch.successful": successful_count,
                    "batch.success_rate": (successful_count / len(requests) if requests else 0),
                }
            )
            span.set_status(Status(StatusCode.OK))

            return results
