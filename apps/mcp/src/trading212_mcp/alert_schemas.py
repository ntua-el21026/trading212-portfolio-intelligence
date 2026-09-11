"""Closed alert WindowPage result; shares the HTTP financial metadata schemas."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator
from trading212_api_contracts.alerts import AlertSchema, AlertSummaryPage
from trading212_api_contracts.targets import Cursor


class AlertToolError(AlertSchema):
    code: Literal[
        "AUTHENTICATION_REQUIRED",
        "ACCESS_DENIED",
        "NOT_FOUND",
        "VALIDATION_FAILED",
        "CURRENCY_MISMATCH",
        "CURSOR_INVALID",
        "COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED",
        "REQUEST_TOO_LARGE",
        "RESULT_TOO_LARGE",
        "RATE_LIMITED",
        "ALERTS_UNAVAILABLE",
        "INTERNAL_ERROR",
    ]
    message: Annotated[str, Field(min_length=1, max_length=240)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=128)]
    retryable: StrictBool
    remediation: Annotated[str, Field(min_length=1, max_length=240)]


class AlertToolPagination(AlertSchema):
    next_cursor: Cursor | None
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    total: Annotated[StrictInt, Field(ge=0)]
    returned: Annotated[StrictInt, Field(ge=0, le=100)]
    truncated: StrictBool


class AlertSummaryToolResult(AlertSchema):
    data: AlertSummaryPage | None
    pagination: AlertToolPagination | None
    error: AlertToolError | None
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def exact_page(self) -> Self:
        if self.data is None:
            if self.error is None or self.pagination is not None:
                raise ValueError("A failed alert read requires its error only.")
        elif self.error is not None or self.pagination is None:
            raise ValueError("An alert page requires its bounded pagination metadata.")
        elif (
            self.pagination.next_cursor != self.data.page.next_cursor
            or self.pagination.limit != self.data.page.limit
            or self.pagination.total != self.data.page.total
            or self.pagination.returned != len(self.data.page.items)
            or self.pagination.truncated != (self.data.page.next_cursor is not None)
        ):
            raise ValueError("The alert page and pagination disagree.")
        return self
