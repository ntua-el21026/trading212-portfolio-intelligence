"""OpenTelemetry integration point with no implicit external exporter."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider


def configure_tracing(
    *,
    service: str,
    span_processors: tuple[SpanProcessor, ...] = (),
) -> TracerProvider:
    if not service or len(service) > 80:
        raise ValueError("service name must be non-empty and bounded")
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service}))
    for processor in span_processors:
        provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    return provider
