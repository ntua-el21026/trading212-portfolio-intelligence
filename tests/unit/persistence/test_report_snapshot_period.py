"""A retrospective period does not change an explicitly selected snapshot's date."""

from dataclasses import replace
from datetime import date, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session
from trading212_application import reports as app
from trading212_persistence.models import PortfolioSnapshotModel
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.report_capture_portfolio import selected_snapshot

from tests.unit.domain.report_factories import AT, selection, uid

pytestmark = pytest.mark.unit


def test_retrospective_period_keeps_the_actual_later_snapshot_valuation() -> None:
    request = replace(selection(), start_date=date(2025, 1, 1), end_date=date(2025, 12, 31))
    snapshot = PortfolioSnapshotModel(
        valuation_at=AT, source_cutoff_at=AT, reporting_currency="EUR"
    )
    session = Mock(spec=Session, scalar=Mock(return_value=snapshot))
    authority = Mock(spec=ReportAuthorization, account_id=uid(1))
    assert selected_snapshot(session, authority, request, now=AT) is snapshot
    assert snapshot.valuation_at == AT
    authority.check.assert_called_once_with(session, now=AT)


@pytest.mark.parametrize("future_valuation", [False, True])
def test_snapshot_or_requested_cutoff_cannot_introduce_future_knowledge(
    future_valuation: bool,
) -> None:
    request = selection()
    snapshot = PortfolioSnapshotModel(
        valuation_at=AT + timedelta(seconds=1) if future_valuation else AT,
        source_cutoff_at=AT,
        reporting_currency="EUR",
    )
    session = Mock(spec=Session, scalar=Mock(return_value=snapshot))
    authority = Mock(spec=ReportAuthorization, account_id=uid(1))
    with pytest.raises(app.ReportServiceError) as denied:
        selected_snapshot(
            session, authority, request, now=AT if future_valuation else AT - timedelta(seconds=1)
        )
    assert denied.value.code is app.ReportServiceErrorCode.VALIDATION_FAILED
