"""Structured logging, metrics, and tracing adapters."""

from .audit import (
    AuthenticationMethod,
    SecurityAuditAction,
    SecurityAuditEvent,
    SecurityAuditOutcome,
    SecurityAuditSink,
    StructuredLogSecurityAuditSink,
    opaque_audit_reference,
)
from .errors import ErrorReporter, NullErrorReporter
from .logging import bind_correlation_id, clear_request_context, configure_logging, logger
from .metrics import MetricsHttpServer, OperationalMetrics
from .tracing import configure_tracing

__version__ = "0.2.0"

__all__ = [
    "AuthenticationMethod",
    "ErrorReporter",
    "MetricsHttpServer",
    "NullErrorReporter",
    "OperationalMetrics",
    "SecurityAuditAction",
    "SecurityAuditEvent",
    "SecurityAuditOutcome",
    "SecurityAuditSink",
    "StructuredLogSecurityAuditSink",
    "bind_correlation_id",
    "clear_request_context",
    "configure_logging",
    "configure_tracing",
    "logger",
    "opaque_audit_reference",
]
