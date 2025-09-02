from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, ValidationError

from app.core.schemas.base import BaseSchema

from .middleware import ValidationMiddleware
from .registry import FunctionRegistry

tracer = trace.get_tracer(__name__)

T = TypeVar("T", bound=BaseModel)


class FunctionCallRequest(BaseSchema):
    function_name: str
    arguments: dict[str, Any]
    context: dict[str, Any] = {}
    execution_timeout: int = 30


class FunctionCallResponse(BaseSchema):
    function_name: str
    success: bool
    result: Any = None
    error: str | None = None
    execution_time_ms: float
    metadata: dict[str, Any] = {}


class FunctionDispatcher:
    def __init__(
        self,
        registry: FunctionRegistry | None = None,
        middleware: ValidationMiddleware | None = None,
    ):
        self._registry = registry or FunctionRegistry()
        self._middleware = middleware or ValidationMiddleware()
        self._active_calls: dict[str, asyncio.Task[Any]] = {}

    async def dispatch(self, request: FunctionCallRequest) -> FunctionCallResponse:
        start_time = datetime.now(UTC)

        with tracer.start_as_current_span("function_dispatch") as span:
            span.set_attributes(
                {
                    "function.name": request.function_name,
                    "function.correlation_id": request.correlation_id,
                    "function.timeout": request.execution_timeout,
                }
            )

            try:
                func_info = self._registry.get_function(request.function_name)
                if not func_info:
                    error_msg = f"Function {request.function_name} not registered"
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    return self._create_error_response(request, error_msg, start_time)

                span.set_attributes(
                    {
                        "function.type": func_info.function_type,
                        "function.input_schema": (
                            func_info.input_schema.__name__ if func_info.input_schema else "None"
                        ),
                        "function.output_schema": (
                            func_info.output_schema.__name__ if func_info.output_schema else "None"
                        ),
                    }
                )

                validated_args = await self._validate_input(
                    request.arguments, func_info.input_schema, span
                )

                result = await self._execute_function(
                    func_info.handler,
                    validated_args,
                    request.context,
                    request.execution_timeout,
                    span,
                )

                validated_result = await self._validate_output(
                    result, func_info.output_schema, span
                )

                execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

                response = FunctionCallResponse(
                    correlation_id=request.correlation_id,
                    function_name=request.function_name,
                    success=True,
                    result=validated_result,
                    execution_time_ms=execution_time,
                    metadata={
                        "function_type": func_info.function_type,
                        "input_validated": (func_info.input_schema is not None),
                        "output_validated": (func_info.output_schema is not None),
                    },
                )

                span.set_attributes(
                    {"function.success": True, "function.execution_time_ms": execution_time}
                )
                span.set_status(Status(StatusCode.OK))

                return response

            except ValidationError as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, f"Validation error: {str(e)}"))
                return self._create_error_response(
                    request, f"Validation error: {str(e)}", start_time
                )

            except TimeoutError:
                error_msg = f"Function execution timeout ({request.execution_timeout}s)"
                span.set_status(Status(StatusCode.ERROR, error_msg))
                return self._create_error_response(request, error_msg, start_time)

            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return self._create_error_response(
                    request, f"Execution error: {str(e)}", start_time
                )

    async def _validate_input(
        self, arguments: dict[str, Any], input_schema: type[BaseModel] | None, span: trace.Span
    ) -> dict[str, Any]:
        if input_schema is None:
            return arguments

        with tracer.start_as_current_span(
            "input_validation", context=trace.set_span_in_context(span)
        ):
            try:
                validated = input_schema(**arguments)
                return validated.model_dump()
            except ValidationError as e:
                span.record_exception(e)
                raise

    async def _validate_output(
        self, result: Any, output_schema: type[BaseModel] | None, span: trace.Span
    ) -> Any:
        if output_schema is None:
            return result

        with tracer.start_as_current_span(
            "output_validation", context=trace.set_span_in_context(span)
        ):
            try:
                if isinstance(result, dict):
                    validated = output_schema(**result)
                    return validated.model_dump()
                elif isinstance(result, BaseModel):
                    return result.model_dump()
                else:
                    return result
            except ValidationError as e:
                span.record_exception(e)
                raise

    async def _execute_function(
        self,
        handler: Callable[..., Any],
        arguments: dict[str, Any],
        context: dict[str, Any],
        timeout: int,
        span: trace.Span,
    ) -> Any:
        with tracer.start_as_current_span(
            "function_execution", context=trace.set_span_in_context(span)
        ):
            if inspect.iscoroutinefunction(handler):
                task = asyncio.create_task(handler(**arguments, **context))
                span_id = f"{span.get_span_context().span_id:016x}"
                self._active_calls[span_id] = task

                try:
                    result = await asyncio.wait_for(task, timeout=timeout)
                    return result
                finally:
                    span_id = f"{span.get_span_context().span_id:016x}"
                    self._active_calls.pop(span_id, None)
            else:
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: handler(**arguments, **context))

    def _create_error_response(
        self, request: FunctionCallRequest, error_message: str, start_time: datetime
    ) -> FunctionCallResponse:
        execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

        return FunctionCallResponse(
            correlation_id=request.correlation_id,
            function_name=request.function_name,
            success=False,
            error=error_message,
            execution_time_ms=execution_time,
            metadata={"error_type": "dispatch_error"},
        )

    async def cancel_execution(self, correlation_id: str) -> bool:
        with tracer.start_as_current_span("function_cancellation") as span:
            span.set_attribute("function.correlation_id", correlation_id)

            for _span_id, task in self._active_calls.items():
                if not task.done():
                    task.cancel()

            cancelled_count = len([t for t in self._active_calls.values() if t.cancelled()])
            span.set_attributes(
                {"cancellation.count": cancelled_count, "cancellation.success": cancelled_count > 0}
            )
            span.set_status(Status(StatusCode.OK))

            return cancelled_count > 0

    def get_active_calls(self) -> dict[str, str]:
        return {
            str(span_id): "running" if not task.done() else "completed"
            for span_id, task in self._active_calls.items()
        }
