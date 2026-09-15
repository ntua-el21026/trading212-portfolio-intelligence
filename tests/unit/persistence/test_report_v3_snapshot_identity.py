"""Profile three binds original snapshot identity without relabeling source money."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.values import CurrencyCode
from trading212_persistence.models import PortfolioSnapshotModel
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.report_capture_portfolio import selected_snapshot
from trading212_persistence.source_store import digest

from tests.unit.domain.report_factories import AT, selection, uid
from tests.unit.domain.report_v3_factories import selection_v3
from tests.unit.persistence.test_report_snapshot_quality import _capture

pytestmark = pytest.mark.unit


def test_original_snapshot_identity_preserves_legacy_report_hashes() -> None:
    legacy = selection()
    requests = (
        legacy,
        replace(legacy, sections=(*legacy.sections, r.ReportSection.RISK), risk_run_id=uid(90)),
        selection_v3(),
    )
    actual = []
    for request in requests:
        builder, _ = _capture(timedelta(0), request=request)
        actual.append(
            next(
                pin.content_digest
                for pin in builder.bindings
                if pin.role is r.ReportInputRole.SNAPSHOT
            )
        )
    # Captured independently using the exact a85d188 capture_portfolio function.
    old = "842904aceb9a29308bddee74157735ab3395cf90e0ddd63f9a69b1ac49513b75"
    assert actual[:2] == [old, old]
    assert actual[2] == digest((str(uid(2)), "a" * 64))
    assert actual[2] != old


@pytest.mark.parametrize("profile", [1, 2, 3])
def test_only_explicit_v3_can_preserve_a_different_original_snapshot_currency(profile: int) -> None:
    legacy = selection()
    request = (
        selection_v3()
        if profile == 3
        else replace(legacy, sections=(*legacy.sections, r.ReportSection.RISK), risk_run_id=uid(90))
        if profile == 2
        else legacy
    )
    request = replace(request, reporting_currency=CurrencyCode("USD"))
    snapshot = PortfolioSnapshotModel(
        valuation_at=AT, source_cutoff_at=AT, reporting_currency="EUR"
    )
    session = Mock(spec=Session, scalar=Mock(return_value=snapshot))
    authority = Mock(spec=ReportAuthorization, account_id=uid(1))
    if profile != 3:
        with pytest.raises(app.ReportServiceError) as denied:
            selected_snapshot(session, authority, request, now=AT)
        assert denied.value.code is app.ReportServiceErrorCode.VALIDATION_FAILED
        return
    assert selected_snapshot(session, authority, request, now=AT) is snapshot
    builder, rows = _capture(timedelta(0), request=request)
    position = rows[f"position.{uid(4)}"]
    assert position["market_value"].currency == CurrencyCode("EUR")
    assert str(position["market_value"].value) == "80"
    assert builder.selection.reporting_currency == CurrencyCode("USD")
    note = builder.notes["snapshot.original_currency"]
    assert note.code == "snapshot_original_currency"
    assert "EUR" in note.text and "USD" in note.text
