"""OpenTelemetry setup and FastAPI / SQLAlchemy instrumentation.

Traces go to CloudWatch on AWS through an OTLP collector, and to Jaeger locally. Spans
carry the correlation ID so a trace and a log line join on the same key.

Agent traces go to LangSmith separately (file 12) and are PII-redacted before leaving
the process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncEngine

_log = structlog.get_logger(__name__)

# Probe endpoints produce a span per second per replica and tell us nothing.
EXCLUDED_URLS: Final = "healthz,readyz,metrics"

_configured = False


def configure_tracing(
    *,
    service: str,
    version: str,
    environment: str,
    otlp_endpoint: str | None,
    enabled: bool = True,
    extra_processor: SpanProcessor | None = None,
) -> None:
    """Install the global tracer provider.

    When `enabled` is false, or no endpoint is configured, spans are dropped and no
    collector connection is attempted. Tests and CI run with tracing off.
    """
    global _configured
    if _configured:
        return

    if not enabled or not otlp_endpoint:
        _log.info("tracing_disabled", service=service)
        _configured = True
        return

    resource = Resource.create(
        {
            "service.name": service,
            "service.version": version,
            "deployment.environment": environment,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True))
    )
    if extra_processor is not None:
        provider.add_span_processor(extra_processor)

    trace.set_tracer_provider(provider)
    _configured = True
    _log.info("tracing_configured", service=service, endpoint=otlp_endpoint)


def instrument_app(app: FastAPI) -> None:
    """Instrument a FastAPI app, excluding the probe endpoints."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls=EXCLUDED_URLS)


def instrument_engine(engine: AsyncEngine) -> None:
    """Instrument a SQLAlchemy async engine."""
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


def get_tracer(name: str) -> trace.Tracer:
    """Return a tracer for a module."""
    return trace.get_tracer(name)


def current_span() -> Span:
    """The active span, or a no-op span when tracing is disabled."""
    return trace.get_current_span()


def annotate_span(**attributes: str | int | float | bool) -> None:
    """Attach attributes to the active span.

    Values are not redacted here: nothing that could be personal data belongs on a span
    attribute in the first place. Pass identifiers and counts, never content.
    """
    span = trace.get_current_span()
    if not span.is_recording():
        return
    for key, value in attributes.items():
        span.set_attribute(f"sarana.{key}", value)


def shutdown_tracing() -> None:
    """Flush and shut down the provider. Called from the lifespan shutdown."""
    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        shutdown()
