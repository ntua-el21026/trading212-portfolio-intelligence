"""Alert exports preserve typed canonical values, proof and bounded dataset metadata."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import cast
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session
from trading212_analytics.alerts import evaluate_alert
from trading212_domain import alerts as a
from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.report_manifest import build_report_manifest, encode_report_manifest
from trading212_domain.report_schema import ALERT_EXPORT_TABLES, table_schema
from trading212_domain.sources import LicensePermission, SourceLicense
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.alert_models import AlertEvaluationModel
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.report_base import report_scopes
from trading212_persistence.report_builder import ReportBuilder
from trading212_persistence.report_capture_alert_values import project_evaluation, project_version
from trading212_persistence.report_capture_alerts import _metadata, _read_evaluation
from trading212_security.principals import AuthorizationError, Scope

from tests.unit.analytics.alert_factories import AT, EUR, capture, uid
from tests.unit.persistence.test_report_capture_builder import Sink

pytestmark = pytest.mark.unit


def fixture() -> tuple[ReportBuilder, Sink, r.ReportContext]:
    sink = Sink()
    builder = ReportBuilder(
        r.ExportSelection(
            account_id=uid(2),
            snapshot_id=uid(4),
            start_date=AT.date(),
            end_date=AT.date(),
            source_cutoff_at=AT,
            reporting_currency=EUR,
            dataset=r.ExportDataset.ALERTS,
            field_set=r.ExportFieldSet.AUDIT,
            format=r.ExportFormat.JSON,
        ),
        owner_id=uid(10),
        valuation_at=AT,
        sink=sink,
    )
    for table in ALERT_EXPORT_TABLES:
        builder.append_dataset_row(table, None)
    return builder, sink, _metadata(builder)


def rows(sink: Sink, table: r.ReportTableKey) -> list[dict[str, r.ReportCell]]:
    return [
        dict(zip((c.key for c in table_schema(table).columns), row.cells, strict=True))
        for chunk in sink.chunks
        if chunk.table is table
        for row in chunk.rows
    ]


@pytest.mark.parametrize("metric", tuple(a.AlertMetric))
def test_all_27_metrics_preserve_actual_type_value_decision_and_definition(
    metric: a.AlertMetric,
) -> None:
    saved = capture(metric)
    result = evaluate_alert(saved)
    builder, sink, context = fixture()
    project_version(builder, context, saved.version)
    project_evaluation(builder, context, evaluation_id=uid(30), captured=saved, result=result)
    summary = builder.finish()
    observed = (
        (result.observation,)
        if result.observation is not None
        else tuple(x.observation for x in result.event_decisions)
    )
    actual = rows(sink, r.ReportTableKey.ALERT_OBSERVATIONS)
    assert len(actual) == len(observed)
    for row, expected in zip(actual, observed, strict=True):
        assert row["observed"].value == expected.value
        assert type(row["observed"].value) is type(expected.value)
        assert row["observed"].currency == (
            expected.currency if expected.kind is a.AlertMetricKind.DECIMAL else None
        )
        assert row["observed_currency"].value == (
            expected.currency.value if expected.currency else None
        )
        assert row["bound"].value == expected.bound.value
        assert row["positive_below_quantum"].value == expected.positive_below_quantum
    rule = rows(sink, r.ReportTableKey.ALERT_PREDICATES)[0]
    assert rule["threshold"].value == saved.version.definition.predicate.threshold
    assert rule["minimum_net_amount"].value == (
        saved.version.definition.predicate.minimum_net_amount.amount
        if saved.version.definition.predicate.minimum_net_amount
        else None
    )
    assert set(t.table for t in summary.header.tables) == set(ALERT_EXPORT_TABLES)
    assert all(t.dataset is r.ExportDataset.ALERTS for t in summary.header.tables)
    manifest = encode_report_manifest(build_report_manifest(summary))
    assert b"comparison_basis" not in manifest
    assert all(b"comparison_basis" not in chunk.canonical_bytes for chunk in sink.chunks)


def test_sources_license_warning_memberships_and_fx_amounts_are_lossless() -> None:
    saved = capture(a.AlertMetric.CASH_AMOUNT)
    license = SourceLicense(
        id=str(uid(50)),
        provider_id=str(uid(51)),
        version="synthetic.v1",
        effective_at=AT - timedelta(days=1),
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=LicensePermission.ALLOWED,
        export=LicensePermission.ALLOWED,
        retention_days=90,
        attribution="Synthetic evidence",
        evidence_key="synthetic.license",
    )
    source = a.AlertSourceReference(
        key="original.fx",
        kind=r.ReportSourceKind.FX_SNAPSHOT,
        subject_id=uid(52),
        content_digest="d" * 64,
        effective_at=AT - timedelta(seconds=10),
        first_observed_at=AT - timedelta(seconds=5),
        provider_id=uid(51),
        license_version_id=uid(50),
        expires_at=AT + timedelta(days=7),
    )
    context = replace(
        saved.contexts[0],
        source_reference_keys=(source.key,),
        coverage=(
            a.AlertCoverageFact(
                key="fx",
                expected_count=1,
                available_count=1,
                complete=True,
                covered_fraction=Decimal("1"),
            ),
        ),
        warnings=(
            a.AlertWarning(
                code="synthetic_warning",
                message="Exact warning",
                source_reference_keys=(source.key,),
            ),
        ),
        assumptions=("Exact assumption",),
        reconciliation_id=uid(55),
    )
    conversion = a.AlertMoneyConversion(
        original=Money(Decimal("2"), EUR),
        reporting_currency=EUR,
        converted=Money(Decimal("2"), EUR),
        comparison_basis=Decimal("2"),
        legs=(),
    )
    saved = replace(
        saved,
        contexts=(context,),
        source_references=(source,),
        licenses=(license,),
        fx_conversions=(conversion,),
    )
    result = evaluate_alert(saved)
    builder, sink, metadata = fixture()
    project_evaluation(builder, metadata, evaluation_id=uid(30), captured=saved, result=result)
    summary = builder.finish()
    assert summary.proof.license_references[0].version_id == uid(50)
    assert summary.proof.source_references[0].content_digest == source.content_digest
    mapping = rows(sink, r.ReportTableKey.ALERT_SOURCE_REFERENCES)[0]
    assert mapping["original_key"].value == source.key
    assert mapping["expires_at"].value == source.expires_at
    assert {row["role"].value for row in rows(sink, r.ReportTableKey.ALERT_CONTEXT_MEMBERS)} == {
        "source",
        "warning_source",
    }
    assert rows(sink, r.ReportTableKey.ALERT_CONTEXT_DETAILS)[0]["reconciliation_id"].value == str(
        uid(55)
    )
    money = rows(sink, r.ReportTableKey.ALERT_FX_CONVERSIONS)[0]
    assert money["original"].value == money["converted"].value == Decimal("2")
    assert money["original"].currency == money["converted"].currency == EUR
    assert all(fact.value.context_key is not None for fact in summary.proof.coverage)
    encode_report_manifest(build_report_manifest(summary))


def test_broker_fx_leg_keeps_actual_source_and_unavailable_provider_snapshot_ids() -> None:
    saved = capture(a.AlertMetric.CASH_AMOUNT)
    source = a.AlertSourceReference(
        key="broker.fx",
        kind=r.ReportSourceKind.BROKER_SOURCE_RECORD,
        subject_id=uid(52),
        content_digest="d" * 64,
        effective_at=AT - timedelta(seconds=10),
        first_observed_at=AT - timedelta(seconds=5),
    )
    usd = CurrencyCode("USD")
    conversion = a.AlertMoneyConversion(
        original=Money(Decimal("2"), usd),
        reporting_currency=EUR,
        converted=Money(Decimal("1.8"), EUR),
        comparison_basis=Decimal("1.8"),
        legs=(
            a.AlertFxLeg(
                base=usd,
                quote=EUR,
                rate=Decimal("0.9"),
                source_reference_key=source.key,
                snapshot_id=None,
                provider_id=None,
                observed_at=source.effective_at,
            ),
        ),
    )
    saved = replace(
        saved,
        source_references=(source,),
        contexts=(replace(saved.contexts[0], source_reference_keys=(source.key,)),),
        fx_conversions=(conversion,),
    )
    builder, sink, metadata = fixture()
    project_evaluation(
        builder, metadata, evaluation_id=uid(30), captured=saved, result=evaluate_alert(saved)
    )
    summary = builder.finish()
    leg = rows(sink, r.ReportTableKey.ALERT_FX_LEGS)[0]
    assert leg["rate"].value == Decimal("0.9")
    assert leg["observed_at"].value == source.effective_at
    assert leg["source_key"].value == summary.proof.source_references[0].key
    assert summary.proof.source_references[0].subject_id == source.subject_id
    notes = {note.key for note in summary.proof.notes}
    for key in ("provider_id", "snapshot_id"):
        assert leg[key].value is None and leg[key].state is r.CellState.UNAVAILABLE
        assert leg[key].reason_key in notes
    encode_report_manifest(build_report_manifest(summary))


def test_unavailable_is_not_zero_and_lower_bound_retains_exact_quantum_state() -> None:
    saved = capture(a.AlertMetric.EFFECTIVE_HHI, scalar=Decimal("0"))
    assert isinstance(saved.payload, a.AlertThresholdInput)
    observed = replace(
        saved.payload.observation.observed,
        bound=a.AlertBound.LOWER_BOUND,
        positive_below_quantum=True,
    )
    saved = replace(
        saved,
        payload=a.AlertThresholdInput(
            observation=replace(saved.payload.observation, observed=observed)
        ),
    )
    builder, sink, context = fixture()
    project_evaluation(
        builder, context, evaluation_id=uid(30), captured=saved, result=evaluate_alert(saved)
    )
    builder.finish()
    row = rows(sink, r.ReportTableKey.ALERT_OBSERVATIONS)[0]
    assert row["observed"].value == Decimal("0") and row["positive_below_quantum"].value is True
    assert next(iter(builder.bounds.values())).kind is r.ReportBoundKind.LOWER_BOUND
    observed = replace(
        observed,
        value=None,
        availability=a.AlertAvailability.UNAVAILABLE,
        quality=QualityState.PARTIAL,
        origin=a.AlertOrigin.UNAVAILABLE,
        positive_below_quantum=False,
        reason=a.AlertReason.MISSING_INPUT,
    )
    saved = replace(
        saved,
        payload=a.AlertThresholdInput(
            observation=a.AlertMetricObservation(observed=observed, comparison_basis=None)
        ),
    )
    builder, sink, context = fixture()
    project_evaluation(
        builder, context, evaluation_id=uid(31), captured=saved, result=evaluate_alert(saved)
    )
    builder.finish()
    row = rows(sink, r.ReportTableKey.ALERT_OBSERVATIONS)[0]
    assert row["observed"].value is None and row["observed"].state is r.CellState.UNAVAILABLE
    assert row["observed"].reason_key in builder.notes


def test_dataset_append_rejects_unselected_table_duplicate_and_row_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder, sink, context = fixture()
    with pytest.raises(DomainError):
        builder.append_dataset_row(r.ReportTableKey.SNAPSHOT_TOTALS, None)
    saved = capture()
    project_version(builder, context, saved.version)
    with pytest.raises(DomainError):
        project_version(builder, context, saved.version)
    monkeypatch.setattr(r, "MAX_REPORT_DATASET_ROWS", 1)
    with pytest.raises(DomainError) as failed:
        project_version(builder, context, replace(saved.version, id=uid(33), version_number=2))
    assert failed.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert sink.chunks == []


def test_export_authorization_precedes_payload_access_and_expired_tombstone_reads_no_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = AT
    row = AlertEvaluationModel(
        id=uid(30), input_id=uid(31), expires_at=AT + timedelta(days=1), purged_at=None
    )
    session = Mock(spec=Session)

    def deny(*args: object, **kwargs: object) -> None:
        assert kwargs["export"] is True
        raise AuthorizationError("access denied")

    monkeypatch.setattr(
        "trading212_persistence.report_capture_alerts.authorize_alert_sources", deny
    )
    with pytest.raises(AuthorizationError):
        _read_evaluation(
            session, cast(ReportAuthorization, object()), row, capture().version, now=now
        )
    session.get.assert_not_called()
    row.expires_at = now
    assert (
        _read_evaluation(
            session, cast(ReportAuthorization, object()), row, capture().version, now=now
        )
        is None
    )
    session.get.assert_not_called()
    assert Scope.ALERTS_READ in report_scopes(dataset="alerts", create=True)
    assert Scope.ALERTS_READ in report_scopes(dataset="alerts", detail=True)
    assert Scope.ALERTS_READ not in report_scopes(dataset="alerts")


def test_derived_copy_deadline_is_minimal_and_does_not_change_canonical_manifest() -> None:
    builder, _, _ = fixture()
    before = encode_report_manifest(build_report_manifest(builder.finish()))
    builder.limit_copy_expiry(AT + timedelta(days=5))
    builder.limit_copy_expiry(AT + timedelta(hours=1))
    builder.limit_copy_expiry(AT + timedelta(days=10))
    summary = builder.finish()
    assert summary.copy_expires_at == AT + timedelta(hours=1)
    assert encode_report_manifest(build_report_manifest(summary)) == before


def test_boolean_dividend_observation_keeps_its_explicit_currency_without_money_cell() -> None:
    saved = capture(a.AlertMetric.POSITIVE_DIVIDEND)
    assert isinstance(saved.payload, a.AlertEventBatchInput)
    original = saved.payload.events[0]
    observation = replace(
        original.observation, observed=replace(original.observation.observed, currency=EUR)
    )
    saved = replace(
        saved, payload=replace(saved.payload, events=(replace(original, observation=observation),))
    )
    builder, sink, context = fixture()
    project_evaluation(
        builder, context, evaluation_id=uid(30), captured=saved, result=evaluate_alert(saved)
    )
    builder.finish()
    row = rows(sink, r.ReportTableKey.ALERT_OBSERVATIONS)[0]
    assert row["observed"].kind is r.CellKind.BOOLEAN and row["observed"].value is True
    assert row["observed"].currency is None and row["observed_currency"].value == "EUR"
