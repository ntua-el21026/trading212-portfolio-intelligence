"""Canonical refresh-command semantics used by durable idempotency boundaries."""

from __future__ import annotations

from trading212_application.refresh_semantics import (
    REFRESH_REQUEST_SCHEMA_VERSION,
    RefreshIdempotencyConflictError,
    RefreshRequestSemantics,
)

REFRESH_TASK_NAME = "portfolio.refresh"
REFRESH_TASK_VERSION = 1
MAX_REFRESH_CONSUMER_EXECUTION_ATTEMPTS = 4
REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE = "refresh_consumer_execution_failed"
INVALID_REFRESH_DISPATCH_ERROR_CODE = "invalid_dispatch_payload"

__all__ = [
    "INVALID_REFRESH_DISPATCH_ERROR_CODE",
    "MAX_REFRESH_CONSUMER_EXECUTION_ATTEMPTS",
    "REFRESH_CONSUMER_EXECUTION_EXHAUSTED_ERROR_CODE",
    "REFRESH_REQUEST_SCHEMA_VERSION",
    "REFRESH_TASK_NAME",
    "REFRESH_TASK_VERSION",
    "RefreshIdempotencyConflictError",
    "RefreshRequestSemantics",
]
