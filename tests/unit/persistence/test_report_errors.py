"""Report bounds retain their typed public error across the persistence boundary."""

import asyncio
from typing import NoReturn

import pytest
from sqlalchemy.orm import sessionmaker
from trading212_application import reports as app
from trading212_domain.errors import DomainError, ErrorCode
from trading212_persistence.report_base import ReportStore

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("domain_code", "service_code"),
    (
        (ErrorCode.INPUT_BOUND_EXCEEDED, app.ReportServiceErrorCode.INPUT_BOUND_EXCEEDED),
        (ErrorCode.VALIDATION_FAILED, app.ReportServiceErrorCode.VALIDATION_FAILED),
    ),
)
def test_domain_errors_keep_bound_identity_and_hide_private_detail(
    domain_code: ErrorCode, service_code: app.ReportServiceErrorCode
) -> None:
    def operation() -> NoReturn:
        raise DomainError(domain_code, "private-provider-detail", "private-source-field")

    store = ReportStore(sessionmaker())
    with pytest.raises(app.ReportServiceError) as failure:
        asyncio.run(store._run(operation))
    assert failure.value.code is service_code
    assert not failure.value.retryable
    assert "private-provider-detail" not in str(failure.value)
    assert "private-source-field" not in str(failure.value)
