"""Full retained risk series and historical source-use relations, without preview caps."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from trading212_domain import historical_results as h
from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.risk_execution import RiskExecutionInput
from trading212_domain.risk_history import RiskHistory
from trading212_domain.risk_result import RiskCalculation

from .report_builder import ReportBuilder
from .report_capture_common import ReportValue, capture_note, capture_row
from .report_capture_historical import _row as historical_row


def _proof(
    builder: ReportBuilder,
    context: r.ReportContext,
    table: r.ReportTableKey,
    key: str,
    values: Mapping[str, ReportValue],
) -> None:
    builder.add_proof(
        r.ReportProofRelation(
            table=table,
            row=capture_row(builder, context, table, key=key, values=values),
        )
    )


def capture_risk_history(
    builder: ReportBuilder,
    context: r.ReportContext,
    risk_context: r.ReportContext,
    value: RiskCalculation,
    execution: RiskExecutionInput,
    prefix: str,
) -> None:
    """Copy all five fixed input tables, including selected tables with zero rows."""
    history, actual = value.history, value.history.canonical_performance_context
    series = (
        history.portfolio,
        *history.assets,
        *((history.benchmark,) if history.benchmark else ()),
    )
    r.report_limit(sum(len(item.intervals) for item in series) <= r.MAX_REPORT_DATASET_ROWS, "rows")

    def row(table: r.ReportTableKey, suffix: str, values: Mapping[str, ReportValue]) -> r.ReportRow:
        return capture_row(builder, context, table, key=f"{prefix}.{suffix}", values=values)

    def put(table: r.ReportTableKey, rows: Iterable[r.ReportRow]) -> None:
        builder.add_table(table, rows)

    put(
        r.ReportTableKey.RISK_RUN_ASSETS_V1,
        (
            row(
                r.ReportTableKey.RISK_RUN_ASSETS_V1,
                f"asset.{i}",
                {
                    "ordinal": i,
                    "instrument_id": asset.instrument_id,
                    "source_series_id": asset.series_id,
                },
            )
            for i, asset in enumerate(execution.assets)
        ),
    )
    put(
        r.ReportTableKey.RISK_SERIES_V1,
        (
            row(
                r.ReportTableKey.RISK_SERIES_V1,
                f"series.{i}",
                {
                    "ordinal": i,
                    "series_key": item.key,
                    "role": item.key if item.key in ("portfolio", "benchmark") else "asset",
                    "instrument_id": None if item.key in ("portfolio", "benchmark") else item.key,
                    "reporting_currency": item.reporting_currency.value,
                    "calendar_id": item.calendar_id,
                    "calendar_version": item.calendar_version,
                    "frequency": item.frequency,
                    "source_cutoff_at": item.source_cutoff_at,
                    "basis": item.basis,
                    "interval_count": len(item.intervals),
                },
            )
            for i, item in enumerate(series)
        ),
    )

    def intervals() -> Iterable[r.ReportRow]:
        for series_index, item in enumerate(series):
            for i, interval in enumerate(item.intervals):
                key = f"{prefix}.interval.{series_index}.{i}"
                # Present excluded/stale values remain present; quality is copied separately.
                reason_key = None
                if interval.reason is not None:
                    reason_key = capture_note(
                        builder,
                        context,
                        key=f"{key}.simple_return.reason",
                        code=interval.reason.value,
                        text=interval.reason.value,
                    )
                cell = r.ReportCell(
                    kind=r.CellKind.DECIMAL,
                    decimal_role=r.DecimalRole.RATIO,
                    value=interval.simple_return,
                    state=r.CellState.UNAVAILABLE
                    if interval.simple_return is None
                    else r.CellState.AVAILABLE,
                    context_key=context.key,
                    reason_key=reason_key,
                    quality=interval.quality,
                    origin=r.ReportMetricOrigin.DERIVED_DETERMINISTIC,
                    coverage_key=context.coverage_set_key,
                    method_key=context.method_key,
                    method_version=context.method_version,
                    provenance_set_key=context.provenance_set_key,
                    note_set_key=context.note_set_key,
                )
                yield capture_row(
                    builder,
                    context,
                    r.ReportTableKey.RISK_INTERVALS_V1,
                    key=key,
                    values={
                        "series_ordinal": series_index,
                        "series_key": item.key,
                        "ordinal": i,
                        "start_at": interval.start_at,
                        "end_at": interval.end_at,
                        "simple_return": cell,
                        "quality": interval.quality,
                        "reason": interval.reason,
                    },
                )

    put(r.ReportTableKey.RISK_INTERVALS_V1, intervals())
    window = actual.window
    put(
        r.ReportTableKey.RISK_HISTORY_CONTEXT_V1,
        (
            row(
                r.ReportTableKey.RISK_HISTORY_CONTEXT_V1,
                "history.context",
                {
                    "account_id": actual.account_id,
                    "input_digest": actual.input_digest,
                    "window_start_date": window.start_date,
                    "window_end_date": window.end_date,
                    "source_cutoff_at": window.source_cutoff_at,
                    "reporting_currency": window.reporting_currency.value,
                    "coverage_policy": window.coverage_policy,
                    "knowledge_policy": window.knowledge_policy,
                    "method_key": actual.method.name,
                    "method_version": actual.method.version,
                    "source_policy_version": actual.source_policy_version,
                    "accounting_policy_version": actual.accounting_policy_version,
                    "quality": actual.quality,
                    "availability": actual.availability,
                    "reconstruction": actual.reconstruction,
                    "schema_version": actual.schema_version,
                },
            ),
        ),
    )

    def members() -> Iterable[r.ReportRow]:
        for i, method in enumerate(actual.primitive_methods):
            yield row(
                r.ReportTableKey.RISK_HISTORY_MEMBERS_V1,
                f"history.method.{i}",
                {
                    "kind": "primitive_method",
                    "ordinal": i,
                    "name": method.name,
                    "version": method.version,
                },
            )
        for i, assumption in enumerate(actual.assumptions):
            yield row(
                r.ReportTableKey.RISK_HISTORY_MEMBERS_V1,
                f"history.assumption.{i}",
                {
                    "kind": "assumption",
                    "ordinal": i,
                    "name": assumption,
                    "version": None,
                },
            )
        for i, warning in enumerate(history.historical_warnings):
            yield row(
                r.ReportTableKey.RISK_HISTORY_MEMBERS_V1,
                f"history.warning.{i}",
                {
                    "kind": "historical_warning",
                    "ordinal": i,
                    "name": warning.value,
                    "version": None,
                },
            )

    put(r.ReportTableKey.RISK_HISTORY_MEMBERS_V1, members())
    for i, issue in enumerate(actual.warnings):
        note_key = f"{context.key}.warning.{i}"
        builder.add_note(
            r.ReportNote(
                key=note_key,
                family=context.family,
                kind=r.ReportNoteKind.WARNING,
                code=issue.reason_code.value,
                text=issue.reason_code.value,
                related_provenance_set_key=f"{note_key}.sources" if issue.reference_ids else None,
            ),
            note_set_key=context.note_set_key,
        )
        _proof(
            builder,
            context,
            r.ReportTableKey.HISTORICAL_WARNING_COVERAGE,
            f"{note_key}.coverage",
            {"note_key": note_key, "coverage_key": issue.coverage_key},
        )
    for i, warning in enumerate(history.historical_warnings):
        capture_note(
            builder,
            context,
            key=f"{context.key}.retained_warning.{i}",
            text=warning.value,
            code=warning.value,
            kind=r.ReportNoteKind.WARNING,
        )
    assumptions = (
        *actual.assumptions,
        f"accounting_policy_version:{actual.accounting_policy_version}",
        f"source_policy_version:{actual.source_policy_version}",
        f"reconstruction:{actual.reconstruction}",
        *(f"primitive_method:{item.name}:{item.version}" for item in actual.primitive_methods),
    )
    for i, assumption in enumerate(assumptions):
        capture_note(
            builder,
            context,
            key=f"{context.key}.assumption.{i}",
            text=assumption,
            code="canonical_method_assumption",
            kind=r.ReportNoteKind.ASSUMPTION,
        )
    for measure in actual.coverage.measures:
        for label, amount in (
            ("expected_count", measure.expected_count),
            ("available_count", measure.available_count),
            ("complete", measure.complete),
        ):
            for target in (context, risk_context):
                builder.add_coverage(
                    r.ReportCoverageFact(
                        set_key=target.coverage_set_key,
                        family=target.family,
                        metric_key=f"{measure.key.value}.{label}",
                        value=r.ReportCell(
                            kind=r.CellKind.BOOLEAN if type(amount) is bool else r.CellKind.INTEGER,
                            value=amount,
                            context_key=target.key,
                        ),
                    )
                )
        for i, reason in enumerate(measure.reasons):
            capture_note(
                builder,
                context,
                key=f"{context.key}.coverage.{measure.key.value}.{i}",
                text=reason.value,
                code=reason.value,
            )


def capture_risk_trace(
    builder: ReportBuilder, context: r.ReportContext, value: RiskHistory
) -> None:
    """Copy every canonical use/conversion; never select presentation timestamps."""
    uses, conversions = value.source_uses, value.conversions
    # Every use writes a consumer row, so this bound is known before emitting any trace.
    r.report_limit(len(uses) <= r.MAX_REPORT_DATASET_ROWS, "rows")
    by_key = {use.use_key: use for use in uses}
    by_conversion = {conversion.conversion_key: conversion for conversion in conversions}
    if len(by_key) != len(uses) or len(by_conversion) != len(conversions):
        fail_validation("Risk source trace identities are duplicated.", field="source_uses")
    for conversion in conversions:
        for ordinal, key in enumerate(conversion.leg_use_keys):
            use = by_key.get(key)
            if (
                not isinstance(use, h.HistoricalObservationUse)
                or use.conversion_leg is None
                or (
                    use.conversion_leg.conversion_key != conversion.conversion_key
                    or use.conversion_leg.ordinal != ordinal
                )
            ):
                fail_validation("Risk conversion lineage is incomplete.", field="source_uses")
    for use in uses:
        if isinstance(use, h.HistoricalObservationUse) and use.conversion_leg is not None:
            referenced_conversion = by_conversion.get(use.conversion_leg.conversion_key)
            if (
                referenced_conversion is None
                or use.use_key not in referenced_conversion.leg_use_keys
            ):
                fail_validation("Risk source conversion is absent.", field="source_uses")
    for ordinal, use in enumerate(uses):
        key = f"{context.key}.use.{ordinal}"
        consumer = historical_row(
            builder,
            context,
            r.ReportTableKey.HISTORICAL_USE_CONSUMERS,
            f"{key}.consumer",
            use.consumer,
            extra={"use_key": use.use_key},
        )
        builder.add_proof(
            r.ReportProofRelation(table=r.ReportTableKey.HISTORICAL_USE_CONSUMERS, row=consumer)
        )
        if isinstance(use, h.HistoricalObservationUse):
            leg = use.conversion_leg
            table = r.ReportTableKey.HISTORICAL_OBSERVATION_USES
            row = historical_row(
                builder,
                context,
                table,
                key,
                use,
                extra={
                    "conversion_key": None if leg is None else leg.conversion_key,
                    "leg_ordinal": None if leg is None else leg.ordinal,
                    "direction": None if leg is None else leg.direction,
                    "base": None if leg is None else leg.base.value,
                    "quote": None if leg is None else leg.quote.value,
                },
            )
        elif isinstance(use, h.HistoricalEvidenceUse):
            table = r.ReportTableKey.HISTORICAL_EVIDENCE_USES
            row = historical_row(builder, context, table, key, use)
        else:
            table = r.ReportTableKey.HISTORICAL_MISSING_USES
            expected = use.expected
            row = historical_row(
                builder,
                context,
                table,
                key,
                extra={
                    "use_key": use.use_key,
                    "role": use.role,
                    "use_at": use.use_at,
                    "knowledge_cutoff_at": use.knowledge_cutoff_at,
                    "expected_kind": expected.kind,
                    "series_id": expected.series_id
                    if isinstance(expected, h.HistoricalExpectedSeries)
                    else None,
                    "base": expected.base.value
                    if isinstance(expected, h.HistoricalExpectedFx)
                    else None,
                    "quote": expected.quote.value
                    if isinstance(expected, h.HistoricalExpectedFx)
                    else None,
                    "calendar_id": use.calendar_ref.id,
                    "calendar_version": use.calendar_ref.version,
                    "expected_session": use.expected_session,
                    "reason": use.reason,
                },
            )
            for index, candidate in enumerate(use.candidate_snapshot_ids):
                _proof(
                    builder,
                    context,
                    r.ReportTableKey.HISTORICAL_USE_CANDIDATES,
                    f"{key}.candidate.{index}",
                    {"use_key": use.use_key, "ordinal": index, "candidate_snapshot_id": candidate},
                )
        builder.add_proof(r.ReportProofRelation(table=table, row=row))
    for ordinal, conversion in enumerate(conversions):
        key = f"{context.key}.conversion.{ordinal}"
        builder.add_proof(
            r.ReportProofRelation(
                table=r.ReportTableKey.HISTORICAL_CONVERSION_USES,
                row=historical_row(
                    builder, context, r.ReportTableKey.HISTORICAL_CONVERSION_USES, key, conversion
                ),
            )
        )
        for index, leg_key in enumerate(conversion.leg_use_keys):
            _proof(
                builder,
                context,
                r.ReportTableKey.HISTORICAL_CONVERSION_LEGS,
                f"{key}.leg.{index}",
                {
                    "conversion_key": conversion.conversion_key,
                    "ordinal": index,
                    "leg_use_key": leg_key,
                },
            )
