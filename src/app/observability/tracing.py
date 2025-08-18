from __future__ import annotations

import os

from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider

_configured: bool = False
_provider: SDKTracerProvider | None = None


def init_tracing(service_name: str = "devops-ai-api") -> None:
    """
    Configure Azure Monitor OpenTelemetry and common instrumentations.
    """
    global _configured, _provider
    if _configured:
        return

    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)

    configure_azure_monitor(
        connection_string=os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"),
    )

    try:
        HTTPXClientInstrumentor().instrument()
    except Exception:
        pass

    try:
        AsyncPGInstrumentor().instrument()
    except Exception:
        pass

    try:
        PymongoInstrumentor().instrument()
    except Exception:
        pass

    provider = trace.get_tracer_provider()
    if isinstance(provider, SDKTracerProvider):
        _provider = provider

    _configured = True


def get_tracer(instrumentation_name: str | None = None) -> trace.Tracer:
    """
    Return a tracer for the given instrumentation name.
    """
    name = instrumentation_name or "app"
    return trace.get_tracer(name)


def is_initialized() -> bool:
    """
    Return True if tracing has been initialized.
    """
    return _provider is not None


def shutdown() -> None:
    """
    Flush and shut down the tracer provider if initialized.
    """
    global _provider, _configured
    if _provider is not None:
        try:
            _provider.shutdown()
        finally:
            _provider = None
            _configured = False
