"""Operational observations contain only fixed categories and bounded scalar values."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import cast

import pytest
from trading212_analytics.xray import calculate_xray
from trading212_application import sources as app
from trading212_application.operational_telemetry import (
    AlertPublicationCounts,
    Operation,
    SourceFamily,
    record_operation,
    record_source_status,
    record_xray_calculation,
)
from trading212_domain.enums import QualityState
from trading212_domain.sources import SourceAvailability, SourcePeriod
from trading212_domain.values import CurrencyCode
from trading212_observability import OperationalMetrics

from tests.unit.analytics.xray_factories import fixture


@pytest.mark.parametrize(
    "operation,outcome",
    [
        (Operation.TARGET_VALIDATION_RESPONSE, "invalid"),
        (Operation.OPTIMIZER_CALCULATION, "infeasible"),
        (Operation.REPORT_RENDER, "failed"),
        (Operation.EXPORT_RENDER, "completed"),
        (Operation.ALERT_EVENTS, "deduplicated"),
        (Operation.EMAIL_DELIVERY, "failed"),
        (Operation.WEBHOOK_DELIVERY, "accepted"),
    ],
)
def test_outcomes_emit_count_and_optional_duration(
    caplog: pytest.LogCaptureFixture, operation: Operation, outcome: str
) -> None:
    caplog.set_level(logging.INFO, logger="trading212.phase2.telemetry")
    record_operation(operation, outcome, duration_seconds=0.125)
    record = caplog.records[-1]
    assert record.getMessage() == "phase2_operation"
    assert record.__dict__["operation"] == operation.value
    assert record.__dict__["outcome"] == outcome
    assert record.__dict__["count"] == 1
    assert record.__dict__["duration_seconds"] == 0.125


def test_unrecognized_labels_and_invalid_numbers_are_rejected_without_echo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = "private-owner@example.invalid"
    caplog.set_level(logging.INFO)
    for operation, outcome in (
        (cast(Operation, canary), "valid"),
        (Operation.TARGET_VALIDATION_RESPONSE, canary),
    ):
        with pytest.raises(ValueError) as error:
            record_operation(operation, outcome)
        assert canary not in str(error.value)
    for invalid in (float("nan"), float("inf"), -1.0):
        with pytest.raises(ValueError):
            record_operation(Operation.REPORT_RENDER, "failed", duration_seconds=invalid)
    with pytest.raises(ValueError):
        record_operation(Operation.ALERT_EVENTS, "created", count=10001)
    assert not caplog.records


def test_current_quality_observations_emit_no_provider_account_source_or_pair_identity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from datetime import UTC, datetime

    at = datetime(2026, 9, 11, tzinfo=UTC)
    snapshot = app.SourceSnapshotSummaryView(
        id="PRIVATE-SNAPSHOT-ID",
        content_digest="f" * 64,
        period=SourcePeriod(start=date(2026, 1, 1), end=date(2026, 1, 2)),
        first_observed_at=at,
        effective_at=at,
        latest_retrieval=None,
        expected_count=2,
        available_count=1,
        quality=QualityState.PARTIAL,
        freshness=app.SourceFreshnessView(state=app.SourceFreshnessState.STALE),
    )
    pair = app.FxPairStatusView(
        provider_id="PRIVATE-PROVIDER",
        license_version_id="PRIVATE-LICENSE",
        base=CurrencyCode("USD"),
        quote=CurrencyCode("EUR"),
        latest_snapshot=snapshot,
        availability=SourceAvailability.PARTIAL,
    )
    caplog.set_level(logging.INFO, logger="trading212.phase2.telemetry")
    record_source_status(SourceFamily.FX, (pair,))
    record = caplog.records[-1]
    assert record.__dict__["freshness"] == "stale"
    assert record.__dict__["coverage"] == "partial"
    record_source_status(SourceFamily.FX, (replace(pair, latest_snapshot=None),))
    assert caplog.records[-1].__dict__["coverage"] == "unavailable"
    rendered = repr([record.__dict__ for record in caplog.records])
    for value in ("PRIVATE-", "USD", "EUR", "f" * 64):
        assert value not in rendered


def test_alert_publication_counts_keep_dedup_and_cooldown_distinct(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="trading212.phase2.telemetry")
    AlertPublicationCounts(created=2, deduplicated=1, cooldown=1).record()
    assert [
        (record.__dict__["outcome"], record.__dict__["count"]) for record in caplog.records
    ] == [
        ("created", 2),
        ("deduplicated", 1),
        ("cooldown", 1),
    ]


@pytest.mark.parametrize("duration", [float("inf"), float("nan"), -1.0])
def test_query_histogram_rejects_nonfinite_or_negative_duration(duration: float) -> None:
    metrics = OperationalMetrics(service="query-bound")
    with pytest.raises(ValueError):
        metrics.observe_database_query(duration, False)
    assert b'outcome="' not in metrics.render()


def test_verified_xray_quality_preserves_unknown_bounds_and_subquantum_presence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    summary = calculate_xray(fixture()).portfolio_summary
    caplog.set_level(logging.INFO, logger="trading212.phase2.telemetry")
    record_xray_calculation(summary)
    assert {record.__dict__["metric"] for record in caplog.records} == {
        "company_coverage",
        "unresolved_exposure",
        "stale_exposure",
    }
    unresolved = next(
        record for record in caplog.records if record.__dict__["metric"] == "unresolved_exposure"
    )
    assert unresolved.__dict__["bucket"] == "positive"
    assert unresolved.__dict__["bound"] == summary.unresolved_weight.bound.value
    subquantum = replace(summary.unresolved_weight, value=Decimal(0), positive_below_quantum=True)
    record_xray_calculation(replace(summary, unresolved_weight=subquantum))
    assert caplog.records[-2].__dict__["bucket"] == "positive_below_quantum"
    for record in caplog.records:
        assert (
            not {"owner_id", "account_id", "source_reference_ids", "currency", "value"}
            & record.__dict__.keys()
        )
