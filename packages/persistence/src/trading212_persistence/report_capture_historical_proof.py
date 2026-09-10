"""Complete fixed historical options and configured composite benchmark proof rows."""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

from trading212_domain import historical as d
from trading212_domain import historical_results as h
from trading212_domain import reports as r

from .report_builder import ReportBuilder
from .report_capture_common import capture_note
from .report_capture_historical import HistoricalValue, _row


def retained_historical_trace(
    value: d.HistoricalInput, result: h.HistoricalCalculation
) -> tuple[tuple[h.HistoricalSourceUse, ...], tuple[h.HistoricalConversionUse, ...]]:
    """Bind reported observations and events without exporting private daily replay steps."""
    window = result.context.window
    instants = {window.start_at, window.end_at}
    if isinstance(result, (h.PerformanceCalculation, h.BenchmarkCalculation)):
        instants.update(point.valuation_at for point in result.points)
        for period in (*result.rolling_returns, *result.calendar_returns):
            instants.update((period.period_start_at, period.period_end_at))
    if isinstance(result, (h.IncomeCalculation, h.CashFlowCalculation)):
        for interval in result.period_rows:
            instants.add(datetime.combine(interval.start_date, time.min, tzinfo=UTC))
            instants.add(
                datetime.combine(interval.end_date + timedelta(days=1), time.min, tzinfo=UTC)
            )
        instants.update(event.economic_at for event in result.events)
    # This includes actual prior-period income events used by the public growth
    # and previous-income metrics. Repeated evidence checks at other daily
    # reconstruction instants do not become additional reported observations.
    event_ids = {
        use.consumer.event_revision_id
        for use in result.source_uses
        if use.consumer.event_revision_id is not None
    }
    instants.update(
        event.identity.economic_at
        for event in value.event_candidates
        if event.identity.revision_id in event_ids
    )
    retained = {use.use_key for use in result.source_uses if use.use_at in instants}
    actions: dict[tuple[str, int, datetime], h.HistoricalObservationUse] = {}
    for use in result.source_uses:
        if isinstance(use, h.HistoricalObservationUse) and use.source_kind == "corporate_action":
            identity = (use.snapshot_id, use.observation_index, use.knowledge_cutoff_at)
            previous = actions.get(identity)
            if (
                previous is None
                or (use.use_key in retained and previous.use_key not in retained)
                or (
                    (use.use_key in retained) == (previous.use_key in retained)
                    and (use.use_at, use.use_key) < (previous.use_at, previous.use_key)
                )
            ):
                actions[identity] = use
    retained.update(use.use_key for use in actions.values())
    conversion_ids = {
        use.conversion_leg.conversion_key
        for use in result.source_uses
        if use.use_key in retained
        and isinstance(use, h.HistoricalObservationUse)
        and use.conversion_leg is not None
    }
    conversions = tuple(
        item
        for item in result.conversions
        if item.use_at in instants or item.conversion_key in conversion_ids
    )
    retained.update(key for item in conversions for key in item.leg_use_keys)
    uses = tuple(use for use in result.source_uses if use.use_key in retained)
    if retained != {use.use_key for use in uses}:
        from trading212_domain.errors import fail_validation

        fail_validation("Reported conversion has no canonical source leg.", field="source_uses")
    return uses, conversions


def capture_historical_semantics(
    builder: ReportBuilder,
    context: r.ReportContext,
    value: d.HistoricalInput,
    result: h.HistoricalCalculation,
) -> None:
    def put(
        table: r.ReportTableKey,
        key: str,
        values: dict[str, HistoricalValue],
        row_context: r.ReportContext = context,
    ) -> None:
        builder.add_proof(
            r.ReportProofRelation(
                table=table,
                row=_row(builder, row_context, table, key, extra=values),
            )
        )

    options = result.options
    calendar = value.selection.reporting_calendar_ref
    put(
        r.ReportTableKey.HISTORICAL_OPTIONS,
        f"{context.key}.options",
        {
            "family": result.family,
            "frequency": options.frequency
            if isinstance(options, (h.PerformanceOptions, h.ComparisonOptions, h.CashFlowOptions))
            else None,
            "return_method": options.method
            if isinstance(options, (h.PerformanceOptions, h.AttributionOptions))
            else None,
            "rolling_window": options.rolling_window
            if isinstance(options, (h.PerformanceOptions, h.ComparisonOptions))
            else None,
            "calendar_period": options.calendar_period
            if isinstance(options, (h.PerformanceOptions, h.ComparisonOptions))
            else None,
            "grouping": options.grouping
            if isinstance(options, (h.IncomeOptions, h.AttributionOptions))
            else None,
            "cash_flow_kind": options.kind if isinstance(options, h.CashFlowOptions) else None,
            "coverage_policy": result.context.window.coverage_policy,
            "knowledge_policy": result.context.window.knowledge_policy,
            "reporting_calendar_id": None if calendar is None else calendar.id,
            "reporting_calendar_version": None if calendar is None else calendar.version,
            "input_schema_version": value.schema_version,
            "input_method_version": value.method_version,
            "result_schema_version": result.context.schema_version,
        },
    )
    for ordinal, warning in enumerate(result.context.warnings):
        put(
            r.ReportTableKey.HISTORICAL_WARNING_COVERAGE,
            f"{context.key}.warning.{ordinal}.coverage",
            {
                "note_key": f"{context.key}.warning.{ordinal}",
                "coverage_key": warning.coverage_key,
            },
        )
    if not isinstance(result, h.BenchmarkCalculation) or result.composite is None:
        return
    composite = result.composite
    child = replace(
        context,
        key=f"{context.key}.composite",
        method_key=composite.method.name,
        method_version=composite.method.version,
        coverage_set_key=f"{context.key}.composite.coverage",
    )
    builder.add_context(child)
    original = value.benchmark_input
    put(
        r.ReportTableKey.BENCHMARK_COMPOSITE,
        f"{child.key}.header",
        {
            "benchmark_version_id": composite.benchmark_version_id,
            "definition_id": None if original is None else original.definition_id,
            "definition_digest": None if original is None else original.content_digest,
            "published_at": None if original is None else original.published_at,
            "reporting_currency": composite.reporting_currency.value,
            "return_basis": composite.return_basis,
            "calendar_id": composite.calendar_ref.id,
            "calendar_version": composite.calendar_ref.version,
            "rebalance_rule": composite.rebalance_rule,
            "start_date": composite.window.start_date,
            "end_date": composite.window.end_date,
            "source_cutoff_at": composite.window.source_cutoff_at,
            "input_digest": composite.input_digest,
            "method_key": composite.method.name,
            "method_version": composite.method.version,
            "component_count": len(composite.inputs),
            "observation_count": len(composite.observations),
        },
        child,
    )
    for measure in composite.coverage.measures:
        for name, amount in (
            ("expected_count", measure.expected_count),
            ("available_count", measure.available_count),
            ("complete", measure.complete),
        ):
            builder.add_coverage(
                r.ReportCoverageFact(
                    set_key=child.coverage_set_key,
                    family=child.family,
                    metric_key=f"{measure.key.value}.{name}",
                    value=r.ReportCell(
                        kind=r.CellKind.BOOLEAN if type(amount) is bool else r.CellKind.INTEGER,
                        value=amount,
                        context_key=child.key,
                    ),
                )
            )
        for ordinal, reason in enumerate(measure.reasons):
            capture_note(
                builder,
                child,
                key=f"{child.key}.{measure.key.value}.reason.{ordinal}",
                text=reason.value,
                code=reason.value,
            )
    for component in composite.inputs:
        key = f"{child.key}.component.{component.source_id}"
        put(
            r.ReportTableKey.BENCHMARK_COMPONENTS,
            key,
            {
                "source_id": component.source_id,
                "weight": component.weight,
                "calendar_id": component.calendar_ref.id,
                "calendar_version": component.calendar_ref.version,
            },
            child,
        )
        for role, identifiers in (
            ("snapshot", component.snapshot_ids),
            ("license", component.license_version_ids),
        ):
            for ordinal, identifier in enumerate(identifiers):
                put(
                    r.ReportTableKey.BENCHMARK_COMPONENT_MEMBERS,
                    f"{key}.{role}.{ordinal}",
                    {
                        "source_id": component.source_id,
                        "role": role,
                        "ordinal": ordinal,
                        "reference_id": identifier,
                    },
                    child,
                )
