"""Exact alert command conversion and validated private response projection."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import Request, Response
from pydantic import BaseModel
from trading212_api_contracts import alerts as wire
from trading212_application.alert_projection import alert_content
from trading212_application.ingestion import IngestionCapability
from trading212_domain import alerts as domain
from trading212_domain.enums import DiscrepancySeverity
from trading212_domain.historical import HistoricalCashFlowKind
from trading212_domain.reports import ReportType
from trading212_domain.values import CurrencyCode, Money

from .target_routes import _error


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value is not None else None


def alert_definition(value: wire.AlertRuleDefinition) -> domain.AlertRuleDefinition:
    data = value.predicate.model_dump()
    threshold = data.get("threshold")
    comparison = data.get("comparison")
    currency = CurrencyCode(data["currency"]) if data.get("currency") is not None else None
    minimum = data.get("minimum_net_amount")
    source_family = data.get("source_family")
    coverage_domain = data.get("domain")
    discrepancy = data.get("discrepancy_severity")
    capability = data.get("capability_family")
    activity = data.get("activity_kind")
    report = data.get("report_type")
    outcome = data.get("outcome")
    predicate = domain.AlertPredicate(
        family=domain.AlertFamily(value.predicate.family),
        metric=domain.AlertMetric(value.predicate.metric),
        comparison=domain.AlertComparison(comparison) if comparison is not None else None,
        threshold=Decimal(threshold) if isinstance(threshold, str) else threshold,
        currency=currency,
        target_version_id=_uuid(data.get("target_version_id")),
        frontier_depth=data.get("frontier_depth"),
        group_node_id=_uuid(data.get("group_node_id")),
        holding_id=_uuid(data.get("holding_id")),
        include_cash=data.get("include_cash"),
        top_n=data.get("top_n"),
        entity_id=_uuid(data.get("entity_id")),
        left_fund_id=_uuid(data.get("left_fund_id")),
        right_fund_id=_uuid(data.get("right_fund_id")),
        source_family=domain.AlertSourceFamily(source_family)
        if source_family is not None
        else None,
        domain=domain.AlertSourceFamily(coverage_domain) if coverage_domain is not None else None,
        source_id=_uuid(data.get("source_id")),
        calendar_version_id=_uuid(data.get("calendar_version_id")),
        discrepancy_severity=DiscrepancySeverity(discrepancy) if discrepancy is not None else None,
        provider_id=_uuid(data.get("provider_id")),
        window_seconds=data.get("window_seconds"),
        capability_family=IngestionCapability(capability) if capability is not None else None,
        instrument_id=_uuid(data.get("instrument_id")),
        minimum_net_amount=Money(Decimal(minimum), currency)
        if minimum is not None and currency is not None
        else None,
        activity_kind=HistoricalCashFlowKind(activity) if activity is not None else None,
        report_type=ReportType(report) if report not in (None, "all") else None,
        outcome=domain.AlertReportOutcome(outcome) if outcome is not None else None,
    )
    schedule = (
        domain.AlertIntervalSchedule(
            anchor_at=value.schedule.anchor_at, interval_seconds=value.schedule.interval_seconds
        )
        if isinstance(value.schedule, wire.AlertIntervalSchedule)
        else domain.AlertDailyUtcSchedule(minute_utc=value.schedule.minute_utc)
    )
    return domain.AlertRuleDefinition(
        name=value.name,
        predicate=predicate,
        schedule=schedule,
        severity=domain.AlertSeverity(value.severity),
        quality_policy=domain.AlertQualityPolicy(value.quality_policy),
        cooldown_seconds=value.cooldown_seconds,
        destination_ids=tuple(UUID(item) for item in value.destination_ids),
        source_policy_version_id=_uuid(value.source_policy_version_id),
        remediation=value.remediation,
    )


def alert_response[T: BaseModel](
    request: Request,
    value: object,
    schema: type[T],
    *,
    status_code: int = 200,
    etag: str | None = None,
) -> Response:
    try:
        payload = schema.model_validate(alert_content(value)).model_dump_json().encode("utf-8")
    except (KeyError, TypeError, ValueError):
        return _error(request, 500, "INTERNAL_ERROR", "The alert operation failed.")
    if len(payload) > 2 * 1024 * 1024:
        return _error(request, 422, "RESULT_TOO_LARGE", "The alert result exceeds its byte bound.")
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
    if etag is not None:
        headers["ETag"] = etag
    # The action revision does not validate changing evaluation/delivery children.
    return Response(
        payload, status_code=status_code, media_type="application/json", headers=headers
    )
