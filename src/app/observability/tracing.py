from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_provider: TracerProvider | None = None


def init(service_name: str) -> None:
    """
    Initialize OpenTelemetry tracing for this process.

    Safe to call multiple times. Subsequent calls are no-ops once initialized.
    """
    global _provider
    if _provider is not None:
        return

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    _provider = provider


def get_tracer(instrumentation_name: str | None = None) -> trace.Tracer:
    """
    Get a typed tracer. Use this from your app code.
    """
    name = instrumentation_name or "app"
    return trace.get_tracer(name)


def is_initialized() -> bool:
    return _provider is not None


def shutdown() -> None:
    """
    Flush and shut down the tracer provider if initialized.
    Call this during graceful shutdown to export remaining spans.
    """
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None
