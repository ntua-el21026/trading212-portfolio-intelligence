"""Current overlays over status-only, physically authorized native result projections."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import intelligence_quality as q
from trading212_application.sources import SourceFreshnessState
from trading212_application.views import Availability, ViewQuality

from . import models as m
from . import xray_run_models as xm
from .intelligence_quality_codec import status_document
from .intelligence_quality_selection import HISTORICAL_KINDS, MAX_PAYLOAD, RetainedSelection
from .planning_models import AnalyticsRunModel

Kind = q.IntelligenceKind
R = q.QualityReason
REASONS: dict[str, R] = {
    "missing_price": R.INPUT_MISSING,
    "missing_fx": R.INPUT_MISSING,
    "missing_opening": R.INPUT_MISSING,
    "missing_input": R.INPUT_MISSING,
    "incomplete_coverage": R.INPUT_MISSING,
    "source_stale": R.SOURCE_STALE,
    "stale_source": R.SOURCE_STALE,
    "source_expired": R.SOURCE_EXPIRED,
    "license_denied": R.SOURCE_LICENSE_DENIED,
    "computation_failed": R.COMPUTATION_FAILED,
    "not_configured": R.SOURCE_NOT_CONFIGURED,
    "unavailable_opening_evidence": R.INPUT_MISSING,
    "unavailable_event_coverage": R.INPUT_MISSING,
    "unavailable_valuation": R.INPUT_MISSING,
    "unavailable_price": R.INPUT_MISSING,
    "unavailable_fx": R.INPUT_MISSING,
    "unavailable_corporate_action_coverage": R.INPUT_MISSING,
    "unavailable_mapping": R.INPUT_MISSING,
    "unavailable_classification": R.INPUT_MISSING,
    "unavailable_cost_basis": R.INPUT_MISSING,
    "unavailable_benchmark_inputs": R.INPUT_MISSING,
    "unavailable_benchmark_alignment": R.INPUT_MISSING,
    "unavailable_source_license": R.SOURCE_LICENSE_DENIED,
    "unavailable_source_retention": R.SOURCE_EXPIRED,
    "historical_source_stale": R.SOURCE_STALE,
    "unavailable_numeric_result": R.COMPUTATION_FAILED,
    "unavailable_opening_reconciliation": R.RECONCILIATION_INCOMPLETE,
}


def empty_metrics(kind: Kind, reason: R, *, blocked: bool = False) -> tuple[q.MetricQuality, ...]:
    return tuple(
        q.MetricQuality(
            key=key,
            recorded_availability=None,
            recorded_quality=None,
            quality_basis="unavailable",
            current_usability="blocked" if blocked else "unavailable",
            freshness=SourceFreshnessState.UNAVAILABLE,
            freshness_basis="unavailable",
            missing_input="unknown",
            license_applicability="unknown",
            reasons=(reason,),
        )
        for key in q.METRIC_KEYS[kind]
    )


def metric_row(
    key: str,
    availability: Availability,
    quality: ViewQuality,
    *,
    basis: Literal["metric", "result_context"] = "metric",
    code: str | None = None,
) -> q.MetricQuality:
    reasons: tuple[R, ...] = ()
    if quality is ViewQuality.FAILED:
        reasons = (R.COMPUTATION_FAILED,)
    elif code is not None:
        reasons = (REASONS.get(code, R.RECORDED_UNAVAILABLE),)
    elif availability is Availability.UNAVAILABLE:
        reasons = (R.RECORDED_UNAVAILABLE,)
    return q.MetricQuality(
        key=key,
        recorded_availability=availability,
        recorded_quality=quality,
        quality_basis=basis,
        current_usability="unavailable"
        if availability is Availability.UNAVAILABLE or quality is ViewQuality.FAILED
        else "usable",
        freshness=SourceFreshnessState.UNAVAILABLE,
        freshness_basis="unavailable",
        missing_input="missing" if R.INPUT_MISSING in reasons else "unknown",
        license_applicability="unknown",
        reasons=reasons,
    )


def project_valuation(
    session: Session, account: UUID, selected: RetainedSelection
) -> tuple[q.MetricQuality, ...]:
    snapshot = m.PortfolioSnapshotModel
    row = session.execute(
        select(
            snapshot.quality_state,
            snapshot.portfolio_total.is_not(None).label("has_total"),
            snapshot.cash_total.is_not(None).label("has_cash"),
            snapshot.invested_total.is_not(None).label("has_positions"),
        ).where(snapshot.id == selected.view.id, snapshot.broker_account_id == account)
    ).one()
    missing_price = (
        session.scalar(
            select(m.SnapshotPositionModel.id)
            .where(
                m.SnapshotPositionModel.snapshot_id == selected.view.id,
                m.SnapshotPositionModel.current_price.is_(None),
            )
            .limit(1)
        )
        is not None
    )
    quality = ViewQuality(row.quality_state)
    present = {
        "portfolio_total": row.has_total,
        "positions": row.has_positions,
        "cash": row.has_cash,
        "current_price": row.has_positions and not missing_price,
        "direct_allocation": row.has_total and row.has_positions,
    }
    return tuple(
        metric_row(
            key,
            Availability.UNAVAILABLE
            if not present[key]
            else Availability.PARTIAL
            if quality is ViewQuality.PARTIAL
            else Availability.AVAILABLE,
            quality,
            basis="result_context",
        )
        for key in q.METRIC_KEYS[Kind.VALUATION]
    )


def decode_metrics(
    session: Session, owner: UUID, account: UUID, kind: Kind, selected: RetainedSelection
) -> tuple[q.MetricQuality, ...]:
    """Caller checks physical current licenses/retention before any BYTEA read."""
    if kind is Kind.VALUATION:
        return project_valuation(session, account, selected)
    stored = session.scalar(
        select(AnalyticsRunModel.canonical_result).where(
            AnalyticsRunModel.owner_id == owner,
            AnalyticsRunModel.broker_account_id == account,
            AnalyticsRunModel.id == selected.view.id,
            AnalyticsRunModel.kind == kind.value,
        )
    )
    if stored is None or len(stored) != selected.payload_bytes or len(stored) > MAX_PAYLOAD:
        raise q.IntelligenceQualityError("QUALITY_UNAVAILABLE")
    if sha256(stored).hexdigest() != selected.view.content_digest:
        raise q.IntelligenceQualityError("QUALITY_UNAVAILABLE")
    if kind is Kind.XRAY:
        # Hash the retained result, but never decode the X-ray trace. Its immutable
        # normalized component is the existing ordinary summary read seam.
        del stored
        stored = session.scalar(
            select(xm.XrayRunModel.canonical_summary).where(
                xm.XrayRunModel.owner_id == owner,
                xm.XrayRunModel.id == selected.native_run_id,
                xm.XrayRunModel.analytics_run_id == selected.view.id,
                xm.XrayRunModel.content_digest == selected.view.content_digest,
                xm.XrayRunModel.sealed_at.is_not(None),
            )
        )
        if stored is None or len(stored) > q.MAX_QUALITY_BYTES:
            raise q.IntelligenceQualityError("QUALITY_UNAVAILABLE")
    try:
        result = status_document(stored, kind)
        if kind is not Kind.XRAY and result.account_id != str(account):
            raise ValueError("Retained result account mismatch.")
        if kind in HISTORICAL_KINDS and result.input_digest != selected.view.input_digest:
            raise ValueError("Retained result input mismatch.")
        return tuple(
            metric_row(row.key, row.availability, row.quality, basis=row.basis, code=row.reason)
            for row in result.metrics
        )
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise q.IntelligenceQualityError("QUALITY_UNAVAILABLE") from exc


def overlay_sources(
    rows: tuple[q.MetricQuality, ...], sources: tuple[q.QualitySource, ...]
) -> tuple[q.MetricQuality, ...]:
    states = {source.freshness.state for source in sources}
    freshness = (
        SourceFreshnessState.STALE
        if SourceFreshnessState.STALE in states
        else (
            SourceFreshnessState.FRESH
            if states == {SourceFreshnessState.FRESH}
            else SourceFreshnessState.UNAVAILABLE
        )
    )
    licenses = {source.license_applicability for source in sources}
    applicability: Literal["licensed", "not_applicable", "unknown"] = (
        "unknown"
        if not licenses or "unknown" in licenses
        else ("licensed" if "licensed" in licenses else "not_applicable")
    )
    return tuple(
        replace(
            row,
            freshness=freshness,
            freshness_basis="required_sources" if sources else "unavailable",
            license_applicability=applicability,
            reasons=tuple(
                dict.fromkeys(
                    (
                        *row.reasons,
                        *(
                            (R.SOURCE_STALE,)
                            if freshness is SourceFreshnessState.STALE
                            else (R.FRESHNESS_POLICY_MISSING,)
                            if freshness is SourceFreshnessState.UNAVAILABLE
                            else ()
                        ),
                    )
                )
            ),
        )
        for row in rows
    )
