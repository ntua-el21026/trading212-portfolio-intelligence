"""Structured JSON logging with mandatory centralized redaction."""

from __future__ import annotations

import json
import logging
from collections.abc import MutableMapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from trading212_security.redaction import RedactingLogFilter, Redactor

_LOG_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "message",
}


class _StructuredJsonFormatter(logging.Formatter):
    def __init__(self, *, service: str, redactor: Redactor) -> None:
        super().__init__()
        self._service = service
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "event": self._redactor.text(record.getMessage()),
            "level": record.levelname.casefold(),
            "logger": record.name,
            "service": self._service,
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
        }
        for key, value in record.__dict__.items():
            if key not in _LOG_RECORD_KEYS and key != "color_message" and not key.startswith("_"):
                payload[key] = self._redactor.value(value, key=key)
        if record.exc_info is not None:
            exception_type = record.exc_info[0]
            if exception_type is not None:
                payload["exception_type"] = exception_type.__name__
        return json.dumps(
            self._redactor.value(payload),
            default=lambda value: f"<{type(value).__name__}>",
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def configure_logging(
    *,
    service: str,
    level: str = "INFO",
    secret_canaries: Sequence[str] = (),
) -> Redactor:
    if not service or len(service) > 80:
        raise ValueError("service name must be non-empty and bounded")
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError("unknown logging level")
    redactor = Redactor(canaries=secret_canaries)
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.addFilter(RedactingLogFilter(redactor))
    handler.setFormatter(_StructuredJsonFormatter(service=service, redactor=redactor))
    root.addHandler(handler)
    root.setLevel(numeric_level)

    def redact_event(
        _: object,
        __: str,
        event_dict: MutableMapping[str, Any],
    ) -> MutableMapping[str, Any]:
        safe = redactor.value(dict(event_dict))
        return cast(MutableMapping[str, Any], safe)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_event,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)
    return redactor


def bind_correlation_id(correlation_id: str) -> None:
    if not correlation_id or len(correlation_id) > 128:
        raise ValueError("correlation ID must be non-empty and bounded")
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()


def logger(name: str) -> structlog.typing.FilteringBoundLogger:
    return cast(structlog.typing.FilteringBoundLogger, structlog.get_logger(name))
