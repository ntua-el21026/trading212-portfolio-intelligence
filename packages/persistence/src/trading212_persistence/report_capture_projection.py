"""Complete immutable projection tables; no path generation or summary recalculation."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, fields, replace
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.projection_serialization import projection_canonical_bytes
from trading212_domain.report_projection_schema import PROJECTION_POINT_MONEY
from trading212_domain.report_v4 import (
    ReportContextSnapshotBinding,
    ReportContextV4,
    ReportProjectionObservedBinding,
    ReportProjectionRunBinding,
    ReportProjectionVersionBinding,
    ReportSelectionV4,
)
from trading212_domain.values import Money

from .projection_input_store import CapturedProjectionInputs
from .projection_result_store import StoredProjectionResult
from .projection_retained_codec import pack_projection_input
from .projection_source_presentation import projection_sources_presentation
from .report_capture_common import ReportValue, capture_note
from .report_capture_projection_cells import ProjectionReportBuilder, ProjectionReportWriter
from .report_capture_projection_sources import (
    capture_projection_source_tables,
    preflight_projection_report_sources,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionReportMetadata(r.ReportRecord):
    run_id: UUID
    input_id: UUID
    assumption: ReportProjectionVersionBinding
    goal: ReportProjectionVersionBinding | None
    created_at: datetime
    completed_at: datetime
    expires_at: datetime
    report_context: ReportContextSnapshotBinding


def projection_report_binding(
    builder: ProjectionReportBuilder,
    captured: CapturedProjectionInputs,
    saved: StoredProjectionResult,
    metadata: ProjectionReportMetadata,
) -> ReportProjectionRunBinding:
    plan = captured.plan
    snapshot = plan.snapshot
    return ReportProjectionRunBinding(
        root_id=metadata.run_id,
        run_id=metadata.run_id,
        input_id=metadata.input_id,
        result_id=saved.id,
        capture_digest=captured.input_digest,
        numerical_input_digest=plan.numerical_input_digest,
        result_digest=saved.content_digest,
        owner_id=builder.owner_id,
        account_id=plan.selection.account_id,
        reporting_currency=plan.inputs.assumptions.reporting_currency,
        assumption=metadata.assumption,
        goal=metadata.goal,
        initial_kind=plan.selection.initial.kind,
        observed=None
        if snapshot is None
        else ReportProjectionObservedBinding(
            snapshot_id=snapshot.snapshot_id,
            snapshot_digest=snapshot.content_digest,
            valuation_at=snapshot.valuation_at,
        ),
        anchor_date=plan.calendar.anchor_date,
        terminal_date=plan.calendar.boundaries[-1],
        months=plan.selection.months,
        path_count=plan.selection.paths,
        retained_point_count=len(plan.selection.retained_months),
        variant_count=len(saved.calculation.variants),
        asset_count=len(plan.inputs.assumptions.assets),
        source_count=len(captured.sources.sources),
        source_cutoff_at=projection_sources_presentation(captured.sources).source_cutoff_at,
        created_at=metadata.created_at,
        calculated_at=saved.created_at,
        completed_at=metadata.completed_at,
        expires_at=metadata.expires_at,
        report_context=metadata.report_context,
    )


def project_projection(
    builder: ProjectionReportBuilder,
    captured: CapturedProjectionInputs,
    saved: StoredProjectionResult,
    metadata: ProjectionReportMetadata,
) -> ReportProjectionRunBinding:
    value, plan, selection = saved.calculation, captured.plan, builder.selection
    if type(selection) is not ReportSelectionV4:
        fail_validation("An explicit profile-four selection is required.", field="selection")
    result_bytes = projection_canonical_bytes(value)
    r.report_limit(
        len(result_bytes)
        + len(captured.stored.canonical_capture)
        + len(captured.stored.canonical_input)
        + sum(len(source.canonical_proof) for source in captured.sources.sources)
        <= r.MAX_REPORT_DOCUMENT_BYTES,
        "complete_proof_bytes",
    )
    point_count = sum(len(path.points) for variant in value.variants for path in variant.paths)
    asset_count = sum(
        len(point.assets)
        for variant in value.variants
        for path in variant.paths
        for point in path.points
    )
    for count in (point_count, asset_count):
        r.report_limit(count <= r.MAX_REPORT_DATASET_ROWS, "rows")
    r.report_limit(len(captured.sources.license_version_ids) <= 256, "licenses")
    if (
        selection.premium_run.run_id != metadata.run_id
        or saved.run_id != metadata.run_id
        or selection.account_id != plan.selection.account_id
        or selection.reporting_currency != plan.inputs.assumptions.reporting_currency
        or captured.stored != pack_projection_input(plan)
        or captured.sources.snapshot != plan.snapshot
        or {
            (source.header.role, source.header.subject_id, source.header.content_digest)
            for source in captured.sources.sources
        }
        != (
            {
                ("calibration", UUID(pin.subject_id), pin.content_digest)
                for pin in plan.assumption_version.content.calibration_pins
            }
            | (
                set()
                if plan.snapshot is None
                else {("initial_snapshot", plan.snapshot.snapshot_id, plan.snapshot.content_digest)}
            )
        )
        or len(captured.sources.sources)
        != len(plan.assumption_version.content.calibration_pins) + int(plan.snapshot is not None)
        or value.inputs != plan.inputs
        or value.input_digest != plan.numerical_input_digest
        or sha256(result_bytes).hexdigest() != saved.content_digest
        or metadata.assumption.version_id != plan.assumption_version.version_id
        or metadata.assumption.content_digest != plan.assumption_version.content_digest
        or (metadata.goal is None) != (plan.goal_version is None)
        or (
            metadata.goal is not None
            and plan.goal_version is not None
            and (
                metadata.goal.version_id != plan.goal_version.version_id
                or metadata.goal.content_digest != plan.goal_version.content_digest
            )
        )
        or (r.ReportSection.GOAL in selection.sections and plan.goal_version is None)
        or metadata.expires_at > captured.expires_at
        or metadata.report_context.snapshot_id != selection.snapshot_id
        or metadata.report_context.source_cutoff_at != selection.source_cutoff_at
        or metadata.report_context.valuation_at != builder.valuation_at
        or not any(
            binding.family is r.ReportFamily.SNAPSHOT
            and binding.role is r.ReportInputRole.SNAPSHOT
            and binding.subject_id == selection.snapshot_id
            and binding.content_digest == metadata.report_context.snapshot_digest
            for binding in builder.bindings
        )
    ):
        fail_validation(
            "Projection report differs from its canonical saved basis.", field="projection_run_id"
        )
    parts = preflight_projection_report_sources(captured.sources.sources)
    binding = projection_report_binding(builder, captured, saved, metadata)
    prefix = f"projection.{metadata.run_id}"
    context = ReportContextV4(
        key=prefix,
        family=r.ReportFamily.PROJECTION,
        method_key=value.method,
        method_version=value.method_version,
        valuation_at=None if plan.snapshot is None else plan.snapshot.valuation_at,
        source_cutoff_at=binding.source_cutoff_at,
        quality=saved.quality,
        provenance_set_key=f"{prefix}.sources",
        coverage_set_key=f"{prefix}.coverage",
        note_set_key=f"{prefix}.notes",
    )
    builder.add_context(context)
    builder.limit_copy_expiry(min(metadata.expires_at, captured.expires_at))
    writer = ProjectionReportWriter(builder, context)
    goal_writer = writer
    if metadata.goal is not None:
        goal_context = replace(
            context, key=f"{prefix}.goal", family=r.ReportFamily.GOAL, method_key="goal_analysis_v1"
        )
        builder.add_context(goal_context)
        goal_writer = ProjectionReportWriter(builder, goal_context)

    def put(
        table: r.ReportTableKey,
        rows: Iterator[dict[str, ReportValue]] | tuple[dict[str, ReportValue], ...],
    ) -> None:
        from trading212_domain.report_projection_schema import GOAL_REPORT_TABLES

        selected_writer = goal_writer if table in GOAL_REPORT_TABLES else writer
        selected_writer.table(
            table,
            (
                (
                    goal_writer
                    if table is r.ReportTableKey.PROJECTION_QUANTILES_V1
                    and row["kind"] == "goal_shortfall"
                    else selected_writer
                ).row(table, ordinal, row)
                for ordinal, row in enumerate(rows)
            ),
        )

    currency = selection.reporting_currency

    def money(amount: object) -> Money:
        from decimal import Decimal

        if not isinstance(amount, Decimal):
            fail_validation("Saved financial value must be a Decimal.", field="money")
        return Money(amount, currency)

    assumption = plan.inputs.assumptions
    pin = binding.observed
    report = metadata.report_context
    basis: dict[str, ReportValue] = {
        "root_id": metadata.run_id,
        "run_id": metadata.run_id,
        "input_id": metadata.input_id,
        "result_id": saved.id,
        "capture_digest": captured.input_digest,
        "numerical_input_digest": plan.numerical_input_digest,
        "result_digest": saved.content_digest,
        "owner_id": builder.owner_id,
        "account_id": selection.account_id,
        "reporting_currency": currency.value,
        "created_at": metadata.created_at,
        "calculated_at": saved.created_at,
        "completed_at": metadata.completed_at,
        "expires_at": metadata.expires_at,
        "initial_kind": plan.selection.initial.kind,
        "initial_value": plan.inputs.initial.value,
        "observed_snapshot_id": None if pin is None else pin.snapshot_id,
        "observed_snapshot_digest": None if pin is None else pin.snapshot_digest,
        "observed_valuation_at": None if pin is None else pin.valuation_at,
        "original_source_cutoff_at": binding.source_cutoff_at,
        "anchor_date": binding.anchor_date,
        "terminal_date": binding.terminal_date,
        "seed": value.inputs.seed,
        "months": value.inputs.months,
        "paths": value.inputs.paths,
        "retained_point_count": len(value.inputs.retained_months),
        "variant_count": len(value.variants),
        "method": value.method,
        "method_version": value.method_version,
        "numeric_profile": value.numeric_profile,
        "sampler": value.sampler,
        "calendar_rule": plan.calendar.rule,
        "capture_schema_version": plan.schema_version,
        "report_context_snapshot_id": report.snapshot_id,
        "report_context_snapshot_digest": report.snapshot_digest,
        "report_context_valuation_at": report.valuation_at,
        "report_context_source_cutoff_at": report.source_cutoff_at,
    }
    writer.table(
        r.ReportTableKey.PROJECTION_BASIS_V1,
        (
            writer.row(
                r.ReportTableKey.PROJECTION_BASIS_V1,
                0,
                basis,
                reasons={"original_source_cutoff_at": "original_source_cutoff_not_supplied"}
                if binding.source_cutoff_at is None
                else None,
            ),
        ),
    )
    definitions = (("assumption", metadata.assumption),) + (
        () if metadata.goal is None else (("goal", metadata.goal),)
    )
    put(
        r.ReportTableKey.PROJECTION_DEFINITIONS_V1,
        (
            {
                "kind": kind,
                **{field.name: getattr(version, field.name) for field in fields(version)},
            }
            for kind, version in definitions
        ),
    )
    put(
        r.ReportTableKey.PROJECTION_ASSUMPTIONS_V1,
        (
            {
                "annual_inflation": assumption.annual_inflation,
                "annual_fee": assumption.annual_fee,
                "annual_tax_drag": assumption.annual_tax_drag,
                "rebalance": assumption.rebalance,
                "reporting_currency": currency.value,
                "asset_count": len(assumption.assets),
                "calibration_count": len(assumption.calibration_pins),
            },
        ),
    )
    allocations = {
        item.key: (index, item.weight) for index, item in enumerate(plan.inputs.allocation)
    }
    put(
        r.ReportTableKey.PROJECTION_ASSETS_V1,
        (
            {
                "ordinal": index,
                **{field.name: getattr(asset, field.name) for field in fields(asset)},
                "initial_ordinal": allocations[asset.key][0],
                "initial_weight": allocations[asset.key][1],
            }
            for index, asset in enumerate(assumption.assets)
        ),
    )
    put(
        r.ReportTableKey.PROJECTION_CORRELATIONS_V1,
        (
            {
                "row_index": i,
                "column_index": j,
                "row_key": assumption.assets[i].key,
                "column_key": assumption.assets[j].key,
                "coefficient": cell,
            }
            for i, row in enumerate(assumption.correlation)
            for j, cell in enumerate(row)
        ),
    )
    indices = {month: index for index, month in enumerate(plan.selection.retained_months)}
    put(
        r.ReportTableKey.PROJECTION_CALENDAR_V1,
        (
            {"month": month, "on": on, "point_index": indices.get(month)}
            for month, on in enumerate(plan.calendar.boundaries)
        ),
    )

    def schedules() -> Iterator[dict[str, ReportValue]]:
        schedules = (("run", plan.selection.schedule),) + (
            () if plan.goal_version is None else (("goal", plan.goal_version.content.schedule),)
        )
        for scope, schedule in schedules:
            yield {
                "scope": scope,
                "kind": "base",
                "ordinal": 0,
                "key": None,
                "on": None,
                "month": None,
                "value": schedule.base_monthly,
                "annual_growth": schedule.annual_growth,
            }
            for index, on in enumerate(schedule.paused_dates):
                yield {
                    "scope": scope,
                    "kind": "pause",
                    "ordinal": index,
                    "key": None,
                    "on": on,
                    "month": plan.calendar.flow_month(on),
                    "value": None,
                    "annual_growth": None,
                }
            for index, entry in enumerate(schedule.entries):
                yield {
                    "scope": scope,
                    "kind": entry.kind,
                    "ordinal": index,
                    "key": entry.key,
                    "on": entry.on,
                    "month": plan.calendar.flow_month(entry.on),
                    "value": entry.value,
                    "annual_growth": None,
                }

    put(r.ReportTableKey.PROJECTION_SCHEDULE_V1, schedules())
    sensitivity = plan.selection.sensitivity
    put(
        r.ReportTableKey.PROJECTION_SENSITIVITY_V1,
        ()
        if sensitivity is None
        else (
            {
                "contribution_delta": sensitivity.contribution_delta,
                "annual_mean_log_delta": sensitivity.annual_mean_log_delta,
            },
        ),
    )
    put(
        r.ReportTableKey.PROJECTION_VARIANTS_V1,
        (
            {
                "variant": item.variant,
                "path_count": len(item.paths),
                "distribution_count": len(item.distributions),
                "goal_present": item.goal is not None,
            }
            for item in value.variants
        ),
    )
    put(
        r.ReportTableKey.PROJECTION_PATHS_V1,
        (
            {
                "variant": item.variant,
                "path_index": path.index,
                "reporting_currency": path.reporting_currency.value,
                "first_unpaid_month": path.first_unpaid_month,
            }
            for item in value.variants
            for path in item.paths
        ),
    )
    put(
        r.ReportTableKey.PROJECTION_POINTS_V1,
        (
            {
                "variant": item.variant,
                "path_index": path.index,
                "point_index": index,
                "month": point.month,
                "on": plan.calendar.boundaries[point.month],
                **{field: money(getattr(point, field)) for field in PROJECTION_POINT_MONEY},
                "funding_failed": point.funding_failed,
                "unpaid_positive_below_quantum": point.unpaid_positive_below_quantum,
            }
            for item in value.variants
            for path in item.paths
            for index, point in enumerate(path.points)
        ),
    )
    put(
        r.ReportTableKey.PROJECTION_POINT_ASSETS_V1,
        (
            {
                "variant": item.variant,
                "path_index": path.index,
                "point_index": index,
                "asset_index": ai,
                "key": asset.key,
                "value": money(asset.value),
            }
            for item in value.variants
            for path in item.paths
            for index, point in enumerate(path.points)
            for ai, asset in enumerate(point.assets)
        ),
    )
    put(
        r.ReportTableKey.PROJECTION_DISTRIBUTIONS_V1,
        (
            {
                "variant": item.variant,
                "month": point.month,
                "on": plan.calendar.boundaries[point.month],
                "nominal_mean": money(point.nominal_mean),
                "real_mean": money(point.real_mean),
                "funding_failed_paths": point.funding_failed_paths,
            }
            for item in value.variants
            for point in item.distributions
        ),
    )

    def quantiles() -> Iterator[dict[str, ReportValue]]:
        for item in value.variants:
            for point in item.distributions:
                for kind, quantile in (("nominal", point.nominal), ("real", point.real)):
                    for index, (probability, amount) in enumerate(
                        zip(quantile.probabilities, quantile.values, strict=True)
                    ):
                        yield {
                            "variant": item.variant,
                            "kind": kind,
                            "month": point.month,
                            "ordinal": index,
                            "probability": probability,
                            "value": money(amount),
                        }
            if item.goal is not None:
                for index, (probability, amount) in enumerate(
                    zip(
                        item.goal.shortfalls.probabilities, item.goal.shortfalls.values, strict=True
                    )
                ):
                    yield {
                        "variant": item.variant,
                        "kind": "goal_shortfall",
                        "month": None,
                        "ordinal": index,
                        "probability": probability,
                        "value": money(amount),
                    }

    put(r.ReportTableKey.PROJECTION_QUANTILES_V1, quantiles())
    put(
        r.ReportTableKey.PROJECTION_HISTOGRAMS_V1,
        (
            {
                "variant": item.variant,
                "basis": basis,
                "observed_minimum": money(histogram.observed_minimum),
                "observed_maximum": money(histogram.observed_maximum),
                "boundary_rule": histogram.boundary_rule,
            }
            for item in value.variants
            for basis, histogram in (
                ("nominal", item.nominal_histogram),
                ("real", item.real_histogram),
            )
        ),
    )
    put(
        r.ReportTableKey.PROJECTION_HISTOGRAM_BINS_V1,
        (
            {
                "variant": item.variant,
                "basis": basis,
                "ordinal": index,
                "lower": money(cell.lower),
                "upper": money(cell.upper),
                "upper_inclusive": cell.upper_inclusive,
                "count": cell.count,
            }
            for item in value.variants
            for basis, histogram in (
                ("nominal", item.nominal_histogram),
                ("real", item.real_histogram),
            )
            for index, cell in enumerate(histogram.bins)
        ),
    )
    goal = plan.goal_version
    put(
        r.ReportTableKey.PROJECTION_GOAL_STATE_V1,
        (
            {
                "available": goal is not None,
                "reason": "no_goal_pinned" if goal is None else None,
                "goal_version_id": None if goal is None else goal.version_id,
                "automatic_goal_acceptance": False,
            },
        ),
    )
    put(
        r.ReportTableKey.PROJECTION_GOAL_DEFINITION_V1,
        ()
        if goal is None
        else (
            {
                "assumption_version_id": goal.content.assumption_version_id,
                "target": goal.content.target,
                "target_date": goal.content.target_date,
                "months": goal.content.months,
                "basis": goal.content.basis,
                "probability_objective": goal.content.probability_objective,
            },
        ),
    )
    put(
        r.ReportTableKey.PROJECTION_GOAL_RESULTS_V1,
        (
            {
                "variant": item.variant,
                **{
                    field.name: money(getattr(item.goal, field.name))
                    if field.name in {"target", "mean_shortfall"}
                    else getattr(item.goal, field.name)
                    for field in fields(item.goal)
                    if field.name != "shortfalls"
                },
            }
            for item in value.variants
            if item.goal is not None
        ),
    )

    def members() -> Iterator[dict[str, ReportValue]]:
        for index, pivot in enumerate(value.numerical_zero_pivots):
            yield {
                "kind": "zero_pivot",
                "ordinal": index,
                "value": pivot,
                "subject_id": None,
                "content_digest": None,
            }
        for index, source in enumerate(assumption.calibration_pins):
            yield {
                "kind": "calibration",
                "ordinal": index,
                "value": None,
                "subject_id": source.subject_id,
                "content_digest": source.content_digest,
            }

    put(r.ReportTableKey.PROJECTION_MEMBERS_V1, members())
    capture_projection_source_tables(writer, parts)
    for family, role, identifier, digest, parent in (
        (
            r.ReportFamily.PROJECTION,
            r.ReportInputRole.INPUT,
            metadata.run_id,
            captured.input_digest,
            None,
        ),
        (
            r.ReportFamily.PROJECTION,
            r.ReportInputRole.RESULT,
            saved.id,
            saved.content_digest,
            metadata.run_id,
        ),
        *(
            (
                r.ReportFamily.PROJECTION if kind == "assumption" else r.ReportFamily.GOAL,
                r.ReportInputRole.POLICY,
                version.version_id,
                version.content_digest,
                version.aggregate_id,
            )
            for kind, version in definitions
        ),
    ):
        builder.add_binding(
            r.ReportBinding(
                family=family,
                role=role,
                subject_id=identifier,
                content_digest=digest,
                parent_id=parent,
                method_key="goal_analysis_v1" if family is r.ReportFamily.GOAL else value.method,
                method_version=value.method_version,
            )
        )
    capture_note(
        builder,
        context,
        key=f"{prefix}.modeled",
        text=(
            "Saved model estimates, not guaranteed forecasts. "
            "Goal objective attainment never automatically accepts a goal."
        ),
        code="model_estimate_not_guaranteed_forecast",
        kind=r.ReportNoteKind.ASSUMPTION,
    )
    return binding
