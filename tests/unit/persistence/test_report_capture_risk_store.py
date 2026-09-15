"""Source deadlines crossed during risk capture preserve the report error boundary."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import reports as app
from trading212_domain.risk_execution import RiskExecutionInput
from trading212_domain.risk_result import RiskCalculation
from trading212_domain.sources import SourceUse
from trading212_persistence import report_capture_risk_store as store
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.risk_inputs import RiskPreflight
from trading212_persistence.risk_service import PostgresRiskService
from trading212_persistence.source_models import SourceSnapshotFields
from trading212_persistence.source_store import SourceStore

from tests.unit.persistence.test_report_capture_risk import captured_input

pytestmark = pytest.mark.unit


def test_source_expiry_only_on_second_copy_traversal_is_a_safe_report_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder, sink, value, execution, metadata = captured_input()
    initial = metadata.completed_at + timedelta(seconds=1)
    deadline = initial + timedelta(seconds=1)
    now = initial
    visits: list[datetime] = []
    physical = SimpleNamespace(
        id=metadata.portfolio_snapshot_id,
        owner_id=builder.owner_id,
        license_version_id=metadata.definition_version_id,
        expires_at=deadline,
    )
    version = SimpleNamespace(
        id=metadata.definition_version_id,
        definition_id=metadata.definition_id,
        version_number=metadata.definition_version_number,
        content_digest=metadata.definition_digest,
    )
    session = Mock(spec=Session)
    # First query resolves the risk definition header; the allowed source traversal
    # then finds no retention event. Expiry short-circuits the second event query.
    session.scalar.side_effect = [version, None]
    sources = Mock(spec=SourceStore)
    sources._now.side_effect = lambda: now
    sources._snapshot_reference.return_value = "price_snapshot_id"
    sources._owned.return_value = physical

    def permit(*args: object, **kwargs: object) -> object:
        visits.append(now)
        return SourceStore._snapshot_permit(
            cast(SourceStore, sources), cast(Session, session), cast(SourceSnapshotFields, physical)
        )

    sources._snapshot_permit.side_effect = permit
    risk = Mock(spec=PostgresRiskService)

    def load(*args: object, **kwargs: object) -> RiskExecutionInput:
        assert kwargs["required_copy_use"] is SourceUse.REPORT
        sources._snapshot_permit(session, physical)
        return execution

    risk._load_inputs.side_effect = load
    monkeypatch.setattr(store, "PostgresRiskService", Mock(return_value=risk))
    monkeypatch.setattr(
        store,
        "authorize_risk_report_metadata",
        Mock(
            return_value=(
                SimpleNamespace(
                    id=metadata.run_id,
                    input_digest=execution.input_digest,
                    created_at=metadata.created_at,
                    expires_at=metadata.expires_at,
                ),
                SimpleNamespace(
                    definition_version_id=metadata.definition_version_id,
                    portfolio_snapshot_id=metadata.portfolio_snapshot_id,
                    historical_input_id=metadata.historical_input_snapshot_id,
                    benchmark_version_id=None,
                    reporting_currency=builder.selection.reporting_currency.value,
                    window_start_at=execution.historical.selection.window.start_at,
                    window_end_at=execution.historical.selection.window.end_at,
                    source_cutoff_at=builder.selection.source_cutoff_at,
                    xray_run_id=None,
                ),
                SimpleNamespace(completed_at=metadata.completed_at),
                SimpleNamespace(id=metadata.result_id, content_digest=metadata.result_digest),
            )
        ),
    )

    def verified(*args: object) -> RiskCalculation:
        nonlocal now
        assert visits == [initial]
        now = deadline
        return value

    monkeypatch.setattr(store, "verify_risk_result", verified)
    monkeypatch.setattr(
        store, "PostgresHistoricalService", Mock(return_value=SimpleNamespace(_sources=sources))
    )
    monkeypatch.setattr(store, "PostgresXrayService", Mock())
    with pytest.raises(app.ReportServiceError) as error:
        store.capture_risk(
            builder,
            cast(Session, session),
            cast(ReportAuthorization, Mock(spec=ReportAuthorization)),
            sessions=cast(sessionmaker[Session], Mock(spec=sessionmaker)),
            clock=lambda: now,
            cursor_signing_key=b"synthetic-report-cursor-key-32byt",
            preflight=cast(RiskPreflight, Mock()),
        )
    assert visits == [initial, deadline]
    assert sink.chunks  # Actual projection precedes the real source helper's expiry check.
    assert error.value.code is app.ReportServiceErrorCode.ACCESS_DENIED
    assert str(error.value) == "Access to the private report is denied."
