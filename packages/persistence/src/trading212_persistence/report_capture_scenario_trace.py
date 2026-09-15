"""Complete canonical replay trace; unlike public history views no instants are filtered."""

from collections.abc import Mapping

from trading212_domain import historical_results as h
from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.scenario_result import ScenarioReplayProof

from .report_builder import ReportBuilder
from .report_capture_common import ReportValue, capture_row
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
            table=table, row=capture_row(builder, context, table, key=key, values=values)
        )
    )


def capture_scenario_trace(
    builder: ReportBuilder, context: r.ReportContext, value: ScenarioReplayProof
) -> None:
    """Copy every canonical use/conversion; never select presentation timestamps."""
    uses, conversions = value.source_uses, value.conversions
    # Every use writes a consumer row, so this bound is known before emitting any trace.
    r.report_limit(len(uses) <= r.MAX_REPORT_DATASET_ROWS, "rows")
    by_key = {use.use_key: use for use in uses}
    by_conversion = {conversion.conversion_key: conversion for conversion in conversions}
    if len(by_key) != len(uses) or len(by_conversion) != len(conversions):
        fail_validation(
            "Scenario replay source trace identities are duplicated.", field="source_uses"
        )
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
                fail_validation(
                    "Scenario replay conversion lineage is incomplete.", field="source_uses"
                )
    for use in uses:
        if isinstance(use, h.HistoricalObservationUse) and use.conversion_leg is not None:
            referenced_conversion = by_conversion.get(use.conversion_leg.conversion_key)
            if (
                referenced_conversion is None
                or use.use_key not in referenced_conversion.leg_use_keys
            ):
                fail_validation("Scenario replay source conversion is absent.", field="source_uses")
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
