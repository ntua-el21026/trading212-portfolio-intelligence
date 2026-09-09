"""Select retained licensed FX routes; delegate all conversion arithmetic to analytics."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from trading212_application.xray import XrayServiceErrorCode
from trading212_domain import xray as d
from trading212_domain.enums import QualityState
from trading212_domain.sources import ObservationState, SourceUse
from trading212_domain.values import CurrencyCode, Instant

from .source_models import (
    FxObservationModel,
    FxSnapshotModel,
    SourceCalendarSessionModel,
    SourceCoverageGapModel,
    SourceExpiryEventModel,
    SourceRetentionWorkModel,
)
from .xray_base import xray_error
from .xray_capture_base import XrayCaptureState
from .xray_ingestion import XrayIngestion


@dataclass(frozen=True, slots=True)
class _StoredFx:
    id: UUID
    snapshot_id: UUID
    session_date: date
    base: str
    quote: str
    rate: Decimal | None
    effective_at: datetime
    created_at: datetime
    state: str
    coverage_gap_id: UUID | None = None


def convert_capture_values(
    service: XrayIngestion,
    session: Session,
    state: XrayCaptureState,
    positions: tuple[d.XrayPosition, ...],
    cash: tuple[d.XrayCash, ...],
    total: d.XrayMoneyMetric,
    reporting: CurrencyCode,
) -> tuple[
    tuple[d.XrayPosition, ...],
    tuple[d.XrayCash, ...],
    d.XrayMoneyMetric,
    tuple[d.XrayLicensedFx, ...],
]:
    from trading212_analytics.xray import convert_xray_money

    roots: tuple[d.XrayPosition | d.XrayCash, ...] = (*positions, *cash)
    currencies = {
        row.reporting_value.value.currency.value
        for row in roots
        if row.reporting_value.value is not None and row.reporting_value.value.currency != reporting
    }
    if total.value is not None and total.value.currency != reporting:
        currencies.add(total.value.currency.value)
    if not currencies:
        return positions, cash, total, ()
    currencies.add(reporting.value)
    if len(currencies) > 32:
        raise xray_error(XrayServiceErrorCode.RESULT_TOO_LARGE)
    rows = session.execute(
        select(FxObservationModel, FxSnapshotModel)
        .join(FxSnapshotModel, FxSnapshotModel.id == FxObservationModel.snapshot_id)
        .where(
            FxSnapshotModel.owner_id == state.owner,
            FxObservationModel.owner_id == state.owner,
            FxSnapshotModel.provider_id.in_(
                tuple(UUID(item) for item in state.policy.provider_selection_policy.provider_order)
            ),
            FxSnapshotModel.first_observed_at <= state.cutoff,
            FxObservationModel.created_at <= state.cutoff,
            FxSnapshotModel.effective_at <= state.snapshot.valuation_at,
            FxObservationModel.effective_at <= state.snapshot.valuation_at,
            or_(FxObservationModel.base.in_(currencies), FxObservationModel.quote.in_(currencies)),
        )
        .order_by(FxObservationModel.id)
        .limit(100_001)
    ).all()
    if len(rows) > 100_000:
        raise xray_error(XrayServiceErrorCode.RESULT_TOO_LARGE)
    retained_rows = [
        (
            _StoredFx(
                item.id,
                item.snapshot_id,
                item.session_date,
                item.base,
                item.quote,
                item.rate,
                item.effective_at,
                item.created_at,
                item.state,
            ),
            snapshot,
        )
        for item, snapshot in rows
    ]
    actual = {(item.snapshot_id, item.base, item.quote, item.session_date) for item, _ in rows}
    gap_base = func.split_part(SourceCoverageGapModel.source_key, ":", 1)
    gap_quote = func.split_part(SourceCoverageGapModel.source_key, ":", 2)
    gap_rows = session.execute(
        select(SourceCoverageGapModel, FxSnapshotModel, SourceCalendarSessionModel.close_at)
        .join(FxSnapshotModel, FxSnapshotModel.id == SourceCoverageGapModel.fx_snapshot_id)
        .join(
            SourceCalendarSessionModel,
            and_(
                SourceCalendarSessionModel.calendar_id == FxSnapshotModel.calendar_id,
                SourceCalendarSessionModel.session_date == SourceCoverageGapModel.session_date,
            ),
        )
        .where(
            SourceCoverageGapModel.owner_id == state.owner,
            FxSnapshotModel.owner_id == state.owner,
            SourceCalendarSessionModel.owner_id == state.owner,
            FxSnapshotModel.provider_id.in_(
                tuple(UUID(item) for item in state.policy.provider_selection_policy.provider_order)
            ),
            FxSnapshotModel.first_observed_at <= state.cutoff,
            SourceCoverageGapModel.created_at <= state.cutoff,
            FxSnapshotModel.effective_at <= state.snapshot.valuation_at,
            SourceCalendarSessionModel.close_at <= state.snapshot.valuation_at,
            SourceCoverageGapModel.source_key.op("~")("^[A-Z]{3}:[A-Z]{3}$"),
            or_(gap_base.in_(currencies), gap_quote.in_(currencies)),
        )
        .order_by(SourceCoverageGapModel.id)
        .limit(100_001 - len(rows))
    ).all()
    if len(rows) + len(gap_rows) > 100_000:
        raise xray_error(XrayServiceErrorCode.RESULT_TOO_LARGE)
    for gap, snapshot, observed_at in gap_rows:
        base, quote = gap.source_key.split(":")
        if (snapshot.id, base, quote, gap.session_date) in actual:
            continue
        retained_rows.append(
            (
                _StoredFx(
                    gap.id,
                    snapshot.id,
                    gap.session_date,
                    base,
                    quote,
                    None,
                    observed_at,
                    gap.created_at,
                    "missing",
                    gap.id,
                ),
                snapshot,
            )
        )
    provider_order = {
        UUID(item): index
        for index, item in enumerate(state.policy.provider_selection_policy.provider_order)
    }
    grouped: dict[tuple[str, str], list[tuple[Any, Any]]] = {}
    for observation, snapshot in retained_rows:
        grouped.setdefault((observation.base, observation.quote), []).append(
            (observation, snapshot)
        )
    selected: dict[tuple[str, str], tuple[Any, Any]] = {}
    for pair, candidates in grouped.items():
        priority = min(provider_order[snapshot.provider_id] for _, snapshot in candidates)
        candidates = [
            (observation, snapshot)
            for observation, snapshot in candidates
            if provider_order[snapshot.provider_id] == priority
        ]
        latest = max(
            (observation.effective_at, snapshot.effective_at, snapshot.revision_order or 0)
            for observation, snapshot in candidates
        )
        choices = [
            (observation, snapshot)
            for observation, snapshot in candidates
            if (observation.effective_at, snapshot.effective_at, snapshot.revision_order or 0)
            == latest
        ]
        # Equal-ranked conflicting source versions do not become UUID tie-breaks.
        if len(choices) == 1:
            selected[pair] = choices[0]

    def route(base: str) -> tuple[tuple[Any, Any, Literal["multiply", "divide"]], ...]:
        if (base, reporting.value) in grouped:
            pair = selected.get((base, reporting.value))
            return () if pair is None else ((*pair, "multiply"),)
        if (reporting.value, base) in grouped:
            pair = selected.get((reporting.value, base))
            return () if pair is None else ((*pair, "divide"),)
        intermediates = sorted(
            {currency for pair in grouped for currency in pair} - {base, reporting.value}
        )
        routes: list[tuple[tuple[Any, Any, Literal["multiply", "divide"]], ...]] = []
        for intermediate in intermediates:
            left = selected.get((base, intermediate))
            left_operation: Literal["multiply", "divide"] = "multiply"
            if left is None and (base, intermediate) not in grouped:
                left = selected.get((intermediate, base))
                left_operation = "divide"
            right = selected.get((intermediate, reporting.value))
            right_operation: Literal["multiply", "divide"] = "multiply"
            if right is None and (intermediate, reporting.value) not in grouped:
                right = selected.get((reporting.value, intermediate))
                right_operation = "divide"
            if (
                left is not None
                and right is not None
                and left[1].id == right[1].id
                and left[0].session_date == right[0].session_date
                and left[0].effective_at == right[0].effective_at
            ):
                # X-ray pins one immutable source snapshot and fixing for both legs.
                routes.append(((*left, left_operation), (*right, right_operation)))
        # An unspecified triangulation choice is ambiguous, never guessed.
        return routes[0] if len(routes) == 1 else ()

    conversions: list[d.XrayLicensedFx] = []

    def convert(
        consumer: str, value: d.XrayMoneyMetric
    ) -> tuple[d.XrayMoneyMetric, tuple[UUID, ...]]:
        if value.value is None or value.value.currency == reporting:
            return value, ()
        chosen = route(value.value.currency.value)
        legs: list[d.XrayFxLeg] = []
        refs: list[UUID] = []
        for observation, snapshot, operation in chosen:
            service._permit(session, state.owner, snapshot.license_version_id, SourceUse.DISPLAY)
            service._permit(session, state.owner, snapshot.license_version_id, SourceUse.STORE)
            if snapshot.expires_at <= service._now() or any(
                session.scalar(
                    select(model.id)
                    .where(model.owner_id == state.owner, model.fx_snapshot_id == snapshot.id)
                    .limit(1)
                )
                is not None
                for model in (SourceExpiryEventModel, SourceRetentionWorkModel)
            ):
                raise xray_error(XrayServiceErrorCode.ACCESS_DENIED)
            reference = state.dependency(
                d.XrayDependencyKind.FX,
                d.XraySubjectKind.SOURCE_RECORD,
                observation.id,
                d.XrayReferenceKind.FX_COVERAGE_GAP
                if observation.coverage_gap_id is not None
                else d.XrayReferenceKind.FX_OBSERVATION,
                observation.id,
                snapshot.id,
                target=("fx_snapshot_id", snapshot.id),
                source=snapshot,
            )
            refs.append(reference)
            evaluated_at = (
                state.snapshot.valuation_at
                if state.policy.freshness_policy.evaluation_basis == "valuation_at"
                else state.cutoff
            )
            quality = QualityState(snapshot.quality)
            if (
                quality is QualityState.FRESH
                and evaluated_at - observation.effective_at
                > timedelta(seconds=state.policy.freshness_policy.stale_after_seconds)
            ):
                quality = QualityState.STALE
            legs.append(
                d.XrayFxLeg(
                    reference,
                    snapshot.id,
                    None if observation.coverage_gap_id is not None else observation.id,
                    CurrencyCode(observation.base),
                    CurrencyCode(observation.quote),
                    observation.rate,
                    Instant(observation.effective_at),
                    Instant(max(snapshot.first_observed_at, observation.created_at)),
                    operation=operation,
                    quality=quality,
                    confidence=None,
                    state=ObservationState(observation.state),
                    coverage_gap_id=observation.coverage_gap_id,
                )
            )
        final_legs = tuple(legs)
        converted = convert_xray_money(value, reporting, legs=final_legs)
        conversions.append(d.XrayLicensedFx(consumer, value, reporting, final_legs))
        return converted, tuple(refs)

    converted_positions: list[d.XrayPosition] = []
    for position in positions:
        result, references = convert(position.root.key, position.reporting_value)
        converted_positions.append(
            replace(position, reporting_value=result, fx_refs=(*position.fx_refs, *references))
        )
    converted_cash: list[d.XrayCash] = []
    for item in cash:
        result, references = convert(item.root.key, item.reporting_value)
        converted_cash.append(
            replace(item, reporting_value=result, fx_refs=(*item.fx_refs, *references))
        )
    converted_total, _ = convert("portfolio_total", total)
    return tuple(converted_positions), tuple(converted_cash), converted_total, tuple(conversions)
