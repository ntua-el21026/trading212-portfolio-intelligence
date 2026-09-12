"""Closed, non-sensitive Phase 2 observations for the existing JSON log pipeline."""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from trading212_domain.alerts import AlertEvaluationOutcome, AlertReason
from trading212_domain.planning import PlanOutcome
from trading212_domain.reports import ReportFailureCode
from trading212_domain.sources import SourceAvailability
from trading212_domain.xray import XrayRatioMetric
from trading212_domain.xray_result import XrayPortfolioSummary

from . import sources

_LOGGER = logging.getLogger("trading212.phase2.telemetry")


class Operation(StrEnum):
    TARGET_VALIDATION_RESPONSE = "target_validation_response"
    OPTIMIZER_CALCULATION = "optimizer_calculation"
    REPORT_RENDER = "report_render"
    EXPORT_RENDER = "export_render"
    REPORT_FAILURE = "report_consumer_failure_recorded"
    EXPORT_FAILURE = "export_consumer_failure_recorded"
    ALERT_EVALUATION = "alert_evaluation_committed"
    ALERT_EVENTS = "alert_event_publication_committed"
    ALERT_FAILURE = "alert_consumer_failure_recorded"
    EMAIL_DELIVERY = "email_delivery_transition_recorded"
    WEBHOOK_DELIVERY = "webhook_delivery_transition_recorded"


_OUTCOMES: dict[Operation, frozenset[str]] = {
    Operation.TARGET_VALIDATION_RESPONSE: frozenset({"valid", "invalid"}),
    Operation.OPTIMIZER_CALCULATION: frozenset(item.value for item in PlanOutcome),
    Operation.REPORT_RENDER: frozenset({"completed", "failed"}),
    Operation.EXPORT_RENDER: frozenset({"completed", "failed"}),
    Operation.REPORT_FAILURE: frozenset(item.value for item in ReportFailureCode),
    Operation.EXPORT_FAILURE: frozenset(item.value for item in ReportFailureCode),
    Operation.ALERT_EVALUATION: frozenset(item.value for item in AlertEvaluationOutcome),
    Operation.ALERT_EVENTS: frozenset({"created", "deduplicated", "cooldown", "latched"}),
    Operation.ALERT_FAILURE: frozenset(item.value for item in AlertReason),
    Operation.EMAIL_DELIVERY: frozenset({"accepted", "retry", "failed", "not_configured"}),
    Operation.WEBHOOK_DELIVERY: frozenset({"accepted", "retry", "failed", "not_configured"}),
}


def record_operation(
    operation: Operation,
    outcome: str,
    *,
    count: int = 1,
    duration_seconds: float | None = None,
) -> None:
    if not isinstance(operation, Operation) or outcome not in _OUTCOMES[operation]:
        raise ValueError("A fixed operational outcome is required.")
    if type(count) is not int or not 0 <= count <= 10000:
        raise ValueError("A bounded operational count is required.")
    values: dict[str, str | int | float] = {
        "operation": operation.value,
        "outcome": outcome,
        "count": count,
    }
    if duration_seconds is not None:
        if (
            isinstance(duration_seconds, bool)
            or not math.isfinite(duration_seconds)
            or duration_seconds < 0
        ):
            raise ValueError("A finite nonnegative duration is required.")
        values["duration_seconds"] = duration_seconds
    _LOGGER.info("phase2_operation", extra=values)


class SourceFamily(StrEnum):
    MARKET = "market"
    FX = "fx"
    BENCHMARK = "benchmark"


def record_source_status(
    family: SourceFamily,
    items: Sequence[sources.SourceSeriesStatusView | sources.FxPairStatusView],
) -> None:
    if not isinstance(family, SourceFamily) or len(items) > 200:
        raise ValueError("A bounded source-status observation is required.")
    # One observation per authorized page; these are not unique source counters.
    for item in items:
        if not isinstance(item.availability, SourceAvailability):
            raise ValueError("A canonical source availability is required.")
        snapshot = item.latest_snapshot
        freshness = (
            sources.SourceFreshnessState.UNAVAILABLE
            if snapshot is None
            else snapshot.freshness.state
        )
        if not isinstance(freshness, sources.SourceFreshnessState):
            raise ValueError("A canonical source freshness state is required.")
        coverage = (
            "unavailable"
            if snapshot is None or snapshot.expected_count == 0
            else "complete"
            if snapshot.available_count == snapshot.expected_count
            else "none"
            if snapshot.available_count == 0
            else "partial"
        )
        _LOGGER.info(
            "phase2_source_status_observed",
            extra={
                "family": family.value,
                "availability": item.availability.value,
                "freshness": freshness.value,
                "coverage": coverage,
                "count": 1,
            },
        )


def _ratio_bucket(metric: XrayRatioMetric) -> str:
    if metric.value is None:
        return "unavailable"
    if metric.value == 0:
        return "positive_below_quantum" if metric.positive_below_quantum else "zero"
    return "one" if metric.value == 1 else "positive"


def record_xray_calculation(summary: XrayPortfolioSummary) -> None:
    # Verified calculation observations, not committed-run counters. Preserve the
    # bound/availability categories so a zero lower bound cannot imply absence.
    for metric_name, metric in (
        ("company_coverage", summary.company_known_weight),
        ("unresolved_exposure", summary.unresolved_weight),
        ("stale_exposure", summary.quality_coverage.stale_weight),
    ):
        _LOGGER.info(
            "phase2_xray_calculation_quality",
            extra={
                "metric": metric_name,
                "bucket": _ratio_bucket(metric),
                "availability": metric.availability.value,
                "bound": metric.bound.value,
                "quality": metric.quality.value,
                "count": 1,
            },
        )


@dataclass(frozen=True, slots=True)
class AlertPublicationCounts:
    created: int = 0
    deduplicated: int = 0
    cooldown: int = 0
    latched: int = 0
    email_unavailable: int = 0
    webhook_unavailable: int = 0

    def record(self) -> None:
        for outcome, count in (
            ("created", self.created),
            ("deduplicated", self.deduplicated),
            ("cooldown", self.cooldown),
            ("latched", self.latched),
        ):
            if count:
                record_operation(Operation.ALERT_EVENTS, outcome, count=count)

        for operation, count in (
            (Operation.EMAIL_DELIVERY, self.email_unavailable),
            (Operation.WEBHOOK_DELIVERY, self.webhook_unavailable),
        ):
            if count:
                record_operation(operation, "not_configured", count=count)
