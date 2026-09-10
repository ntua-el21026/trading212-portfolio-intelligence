"""Capture immutable snapshot values and full direct allocation without preview limits."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import reports as app
from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.report_schema import report_tables
from trading212_domain.values import CurrencyCode

from .models import (
    CalculationRunModel,
    InstrumentModel,
    ListingModel,
    PortfolioSnapshotModel,
    SnapshotCashModel,
    SnapshotPositionModel,
    SourceRecordModel,
)
from .planning_inputs import digest
from .portfolio_service import (
    _position_view,
    _snapshot_quality,
    _snapshot_view,
    _snapshot_weight,
    _warning_text,
)
from .report_authorization import ReportAuthorization
from .report_base import report_error
from .report_builder import ReportBuilder
from .report_capture_common import capture_note, capture_row, capture_stored_warnings, capture_table


def selected_snapshot(
    session: Session,
    authorization: ReportAuthorization,
    selection: r.ReportSelection | r.ExportSelection,
    *,
    now: datetime,
) -> PortfolioSnapshotModel:
    authorization.check(session, now=now)
    snapshot = session.scalar(
        select(PortfolioSnapshotModel).where(
            PortfolioSnapshotModel.id == selection.snapshot_id,
            PortfolioSnapshotModel.broker_account_id == authorization.account_id,
            PortfolioSnapshotModel.source_cutoff_at <= selection.source_cutoff_at,
        )
    )
    if snapshot is None:
        raise report_error(app.ReportServiceErrorCode.NOT_FOUND)
    if (
        snapshot.reporting_currency != selection.reporting_currency.value
        or snapshot.valuation_at > selection.source_cutoff_at
        or selection.source_cutoff_at > now
    ):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    return snapshot


def capture_portfolio(
    builder: ReportBuilder,
    session: Session,
    snapshot: PortfolioSnapshotModel,
) -> None:
    calculation = session.scalar(
        select(CalculationRunModel).where(
            CalculationRunModel.id == snapshot.calculation_run_id,
            CalculationRunModel.broker_account_id == snapshot.broker_account_id,
        )
    )
    if calculation is None:
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    quality = _snapshot_quality(snapshot, now=builder.selection.source_cutoff_at)
    context = r.ReportContext(
        key="context.snapshot",
        family=r.ReportFamily.SNAPSHOT,
        method_key=calculation.calculation_name,
        method_version=calculation.version,
        valuation_at=snapshot.valuation_at,
        source_cutoff_at=snapshot.source_cutoff_at,
        source_at=snapshot.source_cutoff_at,
        quality=QualityState(quality.state.value),
        provenance_set_key="sources.snapshot",
        coverage_set_key="coverage.snapshot",
        note_set_key="notes.snapshot",
    )
    builder.add_context(context)
    if not (
        builder.selection.start_date <= snapshot.valuation_at.date() <= builder.selection.end_date
    ):
        capture_note(
            builder,
            context,
            key="snapshot.outside_period",
            code="snapshot_outside_period",
            kind=r.ReportNoteKind.WARNING,
            text=(
                "The selected portfolio snapshot is valued at "
                f"{snapshot.valuation_at.isoformat()}, "
                "outside the requested historical period. Snapshot totals and allocation describe "
                "that valuation instant. Historical sections retain their own period boundary "
                "valuations and sources; snapshot totals are not period-end balances."
            ),
        )
    view = _snapshot_view(snapshot, now=builder.selection.source_cutoff_at, quality=quality)
    fingerprint = digest(
        (
            snapshot.id,
            snapshot.calculation_run_id,
            view,
            snapshot.coverage,
            snapshot.warnings,
            calculation.output_fingerprint,
        )
    )
    builder.add_binding(
        r.ReportBinding(
            family=r.ReportFamily.SNAPSHOT,
            role=r.ReportInputRole.SNAPSHOT,
            subject_id=snapshot.id,
            content_digest=fingerprint,
            method_key=calculation.calculation_name,
            method_version=calculation.version,
        )
    )
    builder.add_binding(
        r.ReportBinding(
            family=r.ReportFamily.SNAPSHOT,
            role=r.ReportInputRole.CALCULATION,
            subject_id=calculation.id,
            content_digest=calculation.output_fingerprint,
        )
    )
    for kind, identity, source_digest, observed in (
        (r.ReportSourceKind.PORTFOLIO_SNAPSHOT, snapshot.id, fingerprint, snapshot.created_at),
        (
            r.ReportSourceKind.CALCULATION,
            calculation.id,
            calculation.output_fingerprint,
            calculation.calculated_at,
        ),
    ):
        builder.add_reference(
            r.ReportSourceReference(
                key=f"snapshot.{kind.value}.{identity}",
                kind=kind,
                subject_id=identity,
                content_digest=source_digest,
                source_at=snapshot.source_cutoff_at,
                first_observed_at=observed,
            ),
            provenance_set_key=context.provenance_set_key,
        )
    r.report_limit(len(calculation.input_ids) <= r.MAX_REPORT_DATASET_ROWS, "sources")
    for identifier in sorted(set(calculation.input_ids)):
        source = session.scalar(
            select(SourceRecordModel).where(
                SourceRecordModel.id == UUID(identifier),
                SourceRecordModel.broker_account_id == snapshot.broker_account_id,
                SourceRecordModel.observed_at <= snapshot.source_cutoff_at,
            )
        )
        if source is None:
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        builder.add_reference(
            r.ReportSourceReference(
                key=f"snapshot.broker_source_record.{source.id}",
                kind=r.ReportSourceKind.BROKER_SOURCE_RECORD,
                subject_id=source.id,
                content_digest=source.payload_fingerprint,
                source_at=source.source_updated_at or source.observed_at,
                first_observed_at=source.observed_at,
            ),
            provenance_set_key=context.provenance_set_key,
        )
    capture_stored_warnings(builder, context, snapshot.warnings, key="snapshot.warning")
    # The public quality projection adds freshness warnings; retain those too.
    stored_preview = _warning_text(snapshot.warnings)
    for ordinal, warning in enumerate(w for w in quality.warnings if w not in stored_preview):
        capture_note(
            builder,
            context,
            key=f"snapshot.quality_warning.{ordinal}",
            text=warning,
            kind=r.ReportNoteKind.WARNING,
            code="snapshot_quality",
        )
    for ordinal, missing in enumerate(quality.missing_inputs):
        capture_note(builder, context, key=f"snapshot.missing.{ordinal}", text=missing)
    for metric in ("complete", "is_complete", "start_at", "end_at"):
        if metric not in snapshot.coverage:
            continue
        raw = snapshot.coverage[metric]
        if isinstance(raw, bool):
            cell = r.ReportCell(kind=r.CellKind.BOOLEAN, value=raw, context_key=context.key)
        elif isinstance(raw, str):
            cell = r.ReportCell(
                kind=r.CellKind.INSTANT,
                value=datetime.fromisoformat(raw.replace("Z", "+00:00")),
                context_key=context.key,
            )
        elif raw is None:
            reason = capture_note(
                builder,
                context,
                key=f"snapshot.coverage.{metric}",
                text="The snapshot does not bound this coverage endpoint.",
            )
            cell = r.ReportCell(
                kind=r.CellKind.INSTANT,
                value=None,
                state=r.CellState.UNAVAILABLE,
                reason_key=reason,
                context_key=context.key,
            )
        else:
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
        builder.add_coverage(
            r.ReportCoverageFact(
                set_key=context.coverage_set_key,
                family=context.family,
                metric_key=metric,
                value=cell,
            )
        )
    selected = report_tables(builder.selection)
    currency = CurrencyCode(snapshot.reporting_currency)
    if r.ReportTableKey.SNAPSHOT_TOTALS in selected:
        missing_reason = (
            "This metric is not persisted with the immutable portfolio snapshot and "
            "cannot be reconstructed at that historical cutoff."
        )
        row = capture_row(
            builder,
            context,
            r.ReportTableKey.SNAPSHOT_TOTALS,
            key="snapshot.totals",
            currency=currency,
            values={
                "snapshot_id": snapshot.id,
                "valuation_at": snapshot.valuation_at,
                "source_cutoff_at": snapshot.source_cutoff_at,
                "total": view.total_value,
                "cash": view.cash_value,
                "invested": view.invested_value,
                "net_contributions": view.net_contributions,
                "dividends_received": None,
                "realized_profit_loss": None,
                "unrealized_profit_loss": None,
            },
            reasons={
                key: missing_reason
                for key in ("dividends_received", "realized_profit_loss", "unrealized_profit_loss")
            },
        )
        capture_table(builder, r.ReportTableKey.SNAPSHOT_TOTALS, (row,))

    def positions() -> Iterator[tuple[SnapshotPositionModel, ListingModel, InstrumentModel]]:
        query = (
            select(SnapshotPositionModel, ListingModel, InstrumentModel)
            .join(ListingModel, ListingModel.id == SnapshotPositionModel.listing_id)
            .join(InstrumentModel, InstrumentModel.id == ListingModel.instrument_id)
            .where(SnapshotPositionModel.snapshot_id == snapshot.id)
            .order_by(SnapshotPositionModel.listing_id)
            .limit(r.MAX_REPORT_DATASET_ROWS + 1)
        )
        for ordinal, (position, listing, instrument) in enumerate(
            session.execute(query).yield_per(256)
        ):
            r.report_limit(ordinal < r.MAX_REPORT_DATASET_ROWS, "positions")
            yield position, listing, instrument

    def position_rows() -> Iterator[r.ReportRow]:
        for position, listing, instrument in positions():
            item = _position_view(position, listing, instrument, snapshot, quality)
            row = capture_row(
                builder,
                context,
                r.ReportTableKey.POSITIONS,
                key=f"position.{position.id}",
                currency=CurrencyCode(position.currency),
                quality=QualityState(position.quality_state),
                origins={
                    metric: r.ReportMetricOrigin(position.value_origin)
                    for metric in (
                        "quantity",
                        "market_value",
                        "provider_cost_basis",
                        "provider_unrealized_profit_loss",
                    )
                }
                | {"direct_weight": r.ReportMetricOrigin.DERIVED_DETERMINISTIC},
                values={
                    "position_id": position.id,
                    "instrument_id": instrument.id,
                    "listing_id": listing.id,
                    "ticker": item.ticker,
                    "name": item.name,
                    "instrument_type": item.instrument_type,
                    "quantity": item.quantity,
                    "trading_currency": item.trading_currency,
                    "current_price": r.ReportCell(
                        kind=r.CellKind.DECIMAL,
                        value=item.current_price,
                        state=r.CellState.AVAILABLE
                        if item.current_price is not None
                        else r.CellState.UNAVAILABLE,
                        decimal_role=r.DecimalRole.PRICE,
                        currency=CurrencyCode(item.trading_currency),
                        reason_key=None
                        if item.current_price is not None
                        else capture_note(
                            builder,
                            context,
                            key=f"position.{position.id}.price.reason",
                            text="The pinned position does not provide a current price.",
                        ),
                        context_key=context.key,
                        quality=QualityState(position.quality_state),
                        coverage_key=context.coverage_set_key,
                        method_key=context.method_key,
                        method_version=context.method_version,
                        origin=r.ReportMetricOrigin(position.value_origin),
                        provenance_set_key=context.provenance_set_key,
                        note_set_key=context.note_set_key,
                    ),
                    "market_value": item.market_value,
                    "provider_cost_basis": item.provider_cost_basis,
                    "provider_unrealized_profit_loss": item.provider_unrealized_profit_loss,
                    "direct_weight": item.direct_weight,
                },
            )
            builder.add_reference(
                r.ReportSourceReference(
                    key=f"snapshot.position.{position.id}",
                    kind=r.ReportSourceKind.SNAPSHOT_POSITION,
                    subject_id=position.id,
                    parent_id=snapshot.id,
                    content_digest=digest(
                        (
                            row,
                            position.quality_state,
                            position.value_origin,
                            position.provenance,
                        )
                    ),
                    source_at=snapshot.source_cutoff_at,
                ),
                provenance_set_key=context.provenance_set_key,
            )
            yield row

    if r.ReportTableKey.POSITIONS in selected:
        capture_table(builder, r.ReportTableKey.POSITIONS, position_rows())

    def allocation_rows() -> Iterator[r.ReportRow]:
        for position, listing, instrument in positions():
            item = _position_view(position, listing, instrument, snapshot, quality)
            yield capture_row(
                builder,
                context,
                r.ReportTableKey.ALLOCATION_BUCKETS,
                key=f"allocation.position.{position.id}",
                currency=CurrencyCode(position.currency),
                quality=QualityState(position.quality_state),
                origins={
                    "value": r.ReportMetricOrigin(position.value_origin),
                    "weight": r.ReportMetricOrigin.DERIVED_DETERMINISTIC,
                },
                values={
                    "dimension": "direct",
                    "bucket_key": listing.id,
                    "name": item.name,
                    "value": item.market_value,
                    "weight": item.direct_weight,
                    "position_count": 1,
                },
            )
        for ordinal, cash in enumerate(
            session.scalars(
                select(SnapshotCashModel)
                .where(SnapshotCashModel.snapshot_id == snapshot.id)
                .order_by(SnapshotCashModel.currency)
                .limit(r.MAX_REPORT_DATASET_ROWS + 1)
            ).yield_per(256)
        ):
            r.report_limit(ordinal < r.MAX_REPORT_DATASET_ROWS, "cash_rows")
            weight = _snapshot_weight(cash.amount, cash.currency, snapshot)
            row = capture_row(
                builder,
                context,
                r.ReportTableKey.ALLOCATION_BUCKETS,
                key=f"allocation.cash.{cash.id}",
                currency=CurrencyCode(cash.currency),
                quality=QualityState(cash.quality_state),
                origins={
                    "value": r.ReportMetricOrigin(cash.value_origin),
                    "weight": r.ReportMetricOrigin.DERIVED_DETERMINISTIC,
                },
                values={
                    "dimension": "direct",
                    "bucket_key": f"cash.{cash.currency}",
                    "name": f"Cash ({cash.currency})",
                    "value": cash.amount,
                    "weight": weight,
                    "position_count": 0,
                },
            )
            builder.add_reference(
                r.ReportSourceReference(
                    key=f"snapshot.cash.{cash.id}",
                    kind=r.ReportSourceKind.SNAPSHOT_CASH,
                    subject_id=cash.id,
                    parent_id=snapshot.id,
                    content_digest=digest(
                        (row, cash.quality_state, cash.value_origin, cash.provenance)
                    ),
                    source_at=snapshot.source_cutoff_at,
                ),
                provenance_set_key=context.provenance_set_key,
            )
            yield row

    if r.ReportTableKey.ALLOCATION_BUCKETS in selected:
        capture_table(builder, r.ReportTableKey.ALLOCATION_BUCKETS, allocation_rows())
