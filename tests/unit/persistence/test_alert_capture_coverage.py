from datetime import timedelta
from decimal import Decimal
from typing import cast
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session
from trading212_domain import alerts as d
from trading212_domain.sources import SourceUse
from trading212_persistence import source_models as sm
from trading212_persistence.alert_capture_common import AlertCaptureState
from trading212_persistence.alert_capture_coverage import _history, coverage_observation
from trading212_persistence.historical_models import (
    HistoricalDependencyModel,
    HistoricalInputModel,
    HistoricalRunModel,
)
from trading212_persistence.planning_models import AnalyticsRunModel
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.source_service import PostgresSourceService

from tests.unit.analytics.alert_factories import AT, capture, context, uid

pytestmark = pytest.mark.unit


def state(metric: d.AlertMetric) -> AlertCaptureState:
    value = capture(metric)
    result = AlertCaptureState(
        cast(Session, Mock()),
        cast(ReportAuthorization, Mock()),
        value.version,
        AT,
        value.observation_window,
        now=AT + timedelta(hours=1),
        sources=cast(PostgresSourceService, Mock()),
    )
    result.context = context()
    return result


def test_unknown_denominator_never_becomes_zero_and_count_uses_explicit_universe() -> None:
    missing = state(d.AlertMetric.MISSING_FRACTION)
    for fact in (
        d.AlertCoverageFact(key="unknown"),
        d.AlertCoverageFact(key="empty", expected_count=0, available_count=0, complete=True),
    ):
        result = coverage_observation(missing, AT, fact)
        assert result.observation.observed.value is None
        assert result.observation.observed.reason is d.AlertReason.UNKNOWN_DENOMINATOR
    known = d.AlertCoverageFact(key="price", expected_count=4, available_count=3, complete=False)
    assert coverage_observation(missing, AT, known).observation.observed.value == Decimal("0.25")
    assert (
        coverage_observation(
            state(d.AlertMetric.MISSING_COUNT), AT, known
        ).observation.observed.value
        == 1
    )


def test_declared_constituent_mass_supports_fraction_but_does_not_invent_row_count() -> None:
    fact = d.AlertCoverageFact(key="constituents", covered_fraction=Decimal("0.9"), complete=False)
    assert coverage_observation(
        state(d.AlertMetric.MISSING_FRACTION), AT, fact
    ).observation.observed.value == Decimal("0.1")
    assert (
        coverage_observation(
            state(d.AlertMetric.MISSING_COUNT), AT, fact
        ).observation.observed.value
        is None
    )


def test_source_age_uses_scheduled_cutoff_not_execution_clock() -> None:
    result = coverage_observation(
        state(d.AlertMetric.SOURCE_AGE_SECONDS),
        AT - timedelta(seconds=301, microseconds=999999),
        d.AlertCoverageFact(key="source"),
    )
    assert result.observation.observed.value == 301
    assert capture().scheduled_for == AT


@pytest.mark.parametrize("nested", (False, True))
@pytest.mark.parametrize(
    "source_kind", ("license", "price", "fx", "action", "benchmark", "classification")
)
def test_historical_store_permission_precedes_payload_service_and_covers_nested_evidence(
    nested: bool, source_kind: str
) -> None:
    selected = state(d.AlertMetric.MISSING_COUNT)
    session, sources = cast(Mock, selected.session), cast(Mock, selected.sources)
    run = HistoricalRunModel(
        id=uid(7),
        owner_id=selected.version.owner_id,
        sealed=True,
        created_at=AT,
        input_id=uid(8),
        analytics_run_id=uid(9),
    )
    captured = HistoricalInputModel(
        id=uid(8),
        owner_id=selected.version.owner_id,
        broker_account_id=selected.version.account_id,
        created_at=AT,
        source_cutoff_at=AT,
    )
    stored = AnalyticsRunModel(
        id=uid(9),
        owner_id=selected.version.owner_id,
        broker_account_id=selected.version.account_id,
        created_at=AT,
        source_cutoff_at=AT,
        valuation_at=AT,
    )
    retained = [run, captured, stored]
    licensed = HistoricalDependencyModel(license_version_id=uid(10), registered_evidence_id=None)
    physical = {
        "price": ("price_snapshot_id", sm.PriceSnapshotModel),
        "fx": ("fx_snapshot_id", sm.FxSnapshotModel),
        "action": ("action_snapshot_id", sm.CorporateActionSnapshotModel),
        "benchmark": ("benchmark_snapshot_id", sm.BenchmarkSnapshotModel),
    }
    if source_kind in physical:
        attribute, model = physical[source_kind]
        licensed.license_version_id = None
        setattr(licensed, attribute, uid(12))
        retained.append(
            model(id=uid(12), owner_id=selected.version.owner_id, license_version_id=uid(10))
        )
    elif source_kind == "classification":
        licensed.license_version_id = None
        licensed.classification_id = uid(12)
        session.scalar.return_value = uid(10)
    session.get.side_effect = retained
    if nested:
        session.scalars.side_effect = (
            [HistoricalDependencyModel(license_version_id=None, registered_evidence_id=uid(11))],
            [licensed],
        )
    else:
        session.scalars.return_value = [licensed]
    sources._permit.side_effect = RuntimeError("store denied")
    with patch(
        "trading212_persistence.alert_capture_coverage.PostgresHistoricalService"
    ) as factory:
        with pytest.raises(RuntimeError, match="store denied"):
            _history(selected, sessions=Mock(), cursor_signing_key=b"s" * 32)
        factory.assert_not_called()
    assert session.scalars.call_count == (2 if nested else 1)
    sources._permit.assert_called_once_with(
        selected.session, selected.version.owner_id, uid(10), SourceUse.STORE
    )
