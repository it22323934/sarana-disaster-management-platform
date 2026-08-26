"""OpenTelemetry setup: FastAPI + SQLAlchemy instrumentation, OTLP export.

Sampling policy per docs/build-prompts/26-observability.md: 100% in dev, 10% in prod,
and 100% for any trace touching a human gate or a disbursement regardless of sampling —
`gate_or_disbursement_sampler` below is what implements that override.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, Sampler, SamplingResult, TraceIdRatioBased

GATE_EVENT_TYPES = frozenset(
    {
        "sarana.dispatch.signoff.requested",
        "sarana.dispatch.signoff.granted",
        "sarana.dispatch.signoff.rejected",
        "sarana.dispatch.released",
        "sarana.aid.disbursement.released",
    }
)


class GateAwareSampler(Sampler):
    """Wraps a ratio-based sampler; always samples spans whose attributes mark them as
    touching a human gate or a disbursement, regardless of the base sampling ratio."""

    def __init__(self, base_ratio: float) -> None:
        self._base = ParentBased(TraceIdRatioBased(base_ratio))
        self._always = ParentBased(TraceIdRatioBased(1.0))

    def should_sample(  # type: ignore[no-untyped-def]  # matches Sampler's own untyped base signature
        self,
        parent_context,
        trace_id,
        name,
        kind=None,
        attributes=None,
        links=None,
        trace_state=None,
    ) -> SamplingResult:
        event_type = (attributes or {}).get("sarana.event_type")
        touches_gate = event_type in GATE_EVENT_TYPES or bool(
            (attributes or {}).get("sarana.is_disbursement")
        )
        sampler = self._always if touches_gate else self._base
        return sampler.should_sample(
            parent_context, trace_id, name, kind, attributes, links, trace_state
        )

    def get_description(self) -> str:
        return "GateAwareSampler{always-samples gate/disbursement spans}"


def configure_tracing(
    *,
    service: str,
    otlp_endpoint: str,
    sample_ratio: float = 1.0,
) -> TracerProvider:
    """Call once at process startup. Returns the provider so main.py can instrument the
    FastAPI app and the SQLAlchemy engine against it (see instrument_fastapi below)."""
    resource = Resource.create({SERVICE_NAME: service})
    provider = TracerProvider(resource=resource, sampler=GateAwareSampler(sample_ratio))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(provider)
    return provider


def instrument_fastapi(app: object, engine: object | None = None) -> None:
    """Deferred imports so a service that hasn't installed the optional instrumentation
    packages doesn't fail at import time — every service that calls this does have them
    (see this package's pyproject.toml), this just keeps the import graph honest."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]

    if engine is not None:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=engine)
