"""Provider-neutral error reporting boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class ErrorReporter(Protocol):
    def capture(
        self,
        error: BaseException,
        *,
        category: str,
        safe_context: Mapping[str, str],
    ) -> None: ...


class NullErrorReporter:
    def capture(
        self,
        error: BaseException,
        *,
        category: str,
        safe_context: Mapping[str, str],
    ) -> None:
        del error, category, safe_context
