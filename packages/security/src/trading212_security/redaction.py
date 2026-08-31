"""Central structured redaction for logs, errors, and safe metadata."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence

_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|password|secret|credential|api[_-]?key|token)",
    re.IGNORECASE,
)
_BASIC_HEADER = re.compile(r"\bBasic\s+[A-Za-z0-9+/=]+", re.IGNORECASE)
_BEARER_HEADER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_BASE_LOG_RECORD_KEYS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class Redactor:
    def __init__(self, *, canaries: Sequence[str] = ()) -> None:
        self._canaries = tuple(value for value in canaries if value)

    def text(self, value: object) -> str:
        rendered = str(value)
        rendered = _BASIC_HEADER.sub("Basic [REDACTED]", rendered)
        rendered = _BEARER_HEADER.sub("Bearer [REDACTED]", rendered)
        for canary in self._canaries:
            rendered = rendered.replace(canary, "[REDACTED]")
        return rendered

    def value(self, value: object, *, key: str | None = None) -> object:
        if key is not None and _SENSITIVE_KEY.search(key):
            return "[REDACTED]"
        if isinstance(value, Mapping):
            return {str(name): self.value(child, key=str(name)) for name, child in value.items()}
        if isinstance(value, tuple):
            return tuple(self.value(child) for child in value)
        if isinstance(value, list):
            return [self.value(child) for child in value]
        if isinstance(value, str):
            return self.text(value)
        return value


class RedactingLogFilter(logging.Filter):
    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redactor.text(record.msg)
        if isinstance(record.args, Mapping):
            record.args = {
                str(key): self._redactor.value(value, key=str(key))
                for key, value in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(self._redactor.value(value) for value in record.args)
        for key, value in tuple(record.__dict__.items()):
            if key not in _BASE_LOG_RECORD_KEYS:
                record.__dict__[key] = self._redactor.value(value, key=key)
        return True
