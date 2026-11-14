"""Public trace-context extraction preserves valid inputs and rejects oversized values."""

import pytest
from opentelemetry.context import Context
from opentelemetry.trace import INVALID_SPAN_CONTEXT, SpanContext, get_current_span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

pytestmark = pytest.mark.security
TRACE_ID = int("1" * 32, 16)
SPAN_ID = int("2" * 16, 16)


def _extract(header: str) -> SpanContext:
    context = TraceContextTextMapPropagator().extract({"traceparent": header}, context=Context())
    return get_current_span(context).get_span_context()


def _future_header(length: int) -> str:
    prefix = f"01-{TRACE_ID:032x}-{SPAN_ID:016x}-01-"
    return prefix + "a" * (length - len(prefix))


def test_normal_traceparent_preserves_remote_identity_and_sampling() -> None:
    span = _extract(f"00-{TRACE_ID:032x}-{SPAN_ID:016x}-01")

    assert span.is_valid and span.is_remote
    assert span.trace_id == TRACE_ID
    assert span.span_id == SPAN_ID
    assert span.trace_flags.sampled


def test_future_traceparent_at_512_character_boundary_preserves_identity() -> None:
    header = _future_header(512)
    assert len(header) == 512

    span = _extract(header)

    assert span.is_valid and span.is_remote
    assert span.trace_id == TRACE_ID
    assert span.span_id == SPAN_ID
    assert span.trace_flags.sampled


def test_future_traceparent_over_512_characters_is_rejected() -> None:
    header = _future_header(513)
    assert len(header) == 513

    assert _extract(header) == INVALID_SPAN_CONTEXT
