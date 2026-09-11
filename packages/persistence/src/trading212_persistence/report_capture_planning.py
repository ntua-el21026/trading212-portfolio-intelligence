"""Private copies of published targets and canonical drift/manual-plan results."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import fields
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import reports as app
from trading212_domain import planning as d
from trading212_domain import reports as r
from trading212_domain import targets as t
from trading212_domain.enums import QualityState
from trading212_domain.planning_serialization import (
    contribution_plan_result_digest,
    contribution_plan_result_from_json,
)
from trading212_domain.report_schema import report_tables, table_schema
from trading212_domain.values import CurrencyCode, Money

from .planning_models import (
    ContributionPlanModel,
    ContributionPlanRequestModel,
    ContributionPlanResultModel,
)
from .planning_service import PostgresPlanningService
from .report_authorization import ReportAuthorization
from .report_base import report_error
from .report_builder import ReportBuilder
from .report_capture_common import ReportValue, capture_note, capture_row, capture_table
from .report_capture_company import CompanyReportBasis, capture_company_actuals
from .report_capture_plan_input import capture_plan_input, capture_planning_sources
from .target_models import TargetNodeModel, TargetVersionModel, VirtualPortfolioModel


def _values(record: object, table: r.ReportTableKey) -> dict[str, ReportValue]:
    # Only internal dataclasses and this repository's literal schema choose fields.
    return {
        column.key: cast(ReportValue, getattr(record, column.key))
        for column in table_schema(table).columns
    }


def _context(builder: ReportBuilder, value: d.PlanningContext, *, key: str) -> r.ReportContext:
    context = r.ReportContext(
        key=f"context.{key}",
        family=r.ReportFamily.PLANNING,
        method_key=value.method,
        method_version=value.method_version,
        valuation_at=value.as_of,
        source_cutoff_at=value.source_cutoff_at,
        quality=value.quality,
        provenance_set_key=f"sources.{key}",
        coverage_set_key=f"coverage.{key}",
        note_set_key=f"notes.{key}",
    )
    builder.add_context(context)
    for name, cell in (
        (
            "coverage_start_at",
            r.ReportCell(
                kind=r.CellKind.INSTANT, value=value.coverage_start_at, context_key=context.key
            ),
        ),
        (
            "coverage_end_at",
            r.ReportCell(
                kind=r.CellKind.INSTANT, value=value.coverage_end_at, context_key=context.key
            ),
        ),
        (
            "reconciled",
            r.ReportCell(kind=r.CellKind.BOOLEAN, value=value.reconciled, context_key=context.key),
        ),
        (
            "availability",
            r.ReportCell(
                kind=r.CellKind.ENUM, value=value.availability.value, context_key=context.key
            ),
        ),
    ):
        builder.add_coverage(
            r.ReportCoverageFact(
                set_key=context.coverage_set_key,
                family=context.family,
                metric_key=name,
                value=cell,
            )
        )
    capture_planning_sources(builder, context, value.sources, key=key)
    for ordinal, missing in enumerate(value.missing_inputs):
        capture_note(builder, context, key=f"{key}.missing.{ordinal}", text=missing)
    if value.reason_code is not None:
        capture_note(
            builder,
            context,
            key=f"{key}.availability",
            text=value.reason_code,
            code=value.reason_code,
        )
    for kind, explanations in (
        (r.ReportNoteKind.WARNING, value.warnings),
        (r.ReportNoteKind.ASSUMPTION, value.assumptions),
    ):
        for ordinal, explanation in enumerate(explanations):
            note_key = f"{key}.{kind.value}.{ordinal}"
            capture_note(
                builder,
                context,
                key=note_key,
                text=explanation.message,
                kind=kind,
                code=explanation.code,
            )
            _explanation_members(builder, context, note_key, explanation)
    for field in fields(value.coverage):
        raw = getattr(value.coverage, field.name)
        if field.name == "basis":
            capture_note(
                builder,
                context,
                key=f"{key}.coverage.basis",
                text=str(raw),
                kind=r.ReportNoteKind.ASSUMPTION,
                code="coverage_basis",
            )
            continue
        # Reuse the canonical scalar mapper through a one-cell metric schema.
        if isinstance(raw, bool):
            cell = r.ReportCell(kind=r.CellKind.BOOLEAN, value=raw, context_key=context.key)
        else:
            money = isinstance(raw, Money)
            cell = r.ReportCell(
                kind=r.CellKind.DECIMAL,
                value=raw.amount if money else raw,
                decimal_role=r.DecimalRole.MONEY
                if money or field.name == "denominator"
                else r.DecimalRole.RATIO,
                currency=raw.currency
                if money
                else CurrencyCode(value.reporting_currency)
                if field.name == "denominator"
                else None,
                context_key=context.key,
                state=r.CellState.AVAILABLE if raw is not None else r.CellState.UNAVAILABLE,
                reason_key=None
                if raw is not None
                else capture_note(
                    builder,
                    context,
                    key=f"{key}.coverage.{field.name}.reason",
                    text=value.reason_code or "Canonical planning coverage is unavailable.",
                ),
            )
        builder.add_coverage(
            r.ReportCoverageFact(
                set_key=context.coverage_set_key,
                family=context.family,
                metric_key=field.name,
                value=cell,
            )
        )
    return context


def _relation(
    builder: ReportBuilder,
    context: r.ReportContext,
    *,
    kind: str,
    parent: str,
    ordinal: int,
    member: str,
) -> r.ReportRow:
    return capture_row(
        builder,
        context,
        r.ReportTableKey.PLAN_RELATIONS,
        key=f"{parent}.{kind}.{ordinal}",
        values={
            "relation_kind": kind,
            "parent_key": parent,
            "ordinal": ordinal,
            "member_key": member,
        },
    )


def _explanation_members(
    builder: ReportBuilder,
    context: r.ReportContext,
    key: str,
    explanation: d.PlanningExplanation,
) -> None:
    for kind, members in (
        ("node", explanation.node_keys),
        ("constraint", explanation.constraint_keys),
    ):
        for ordinal, member in enumerate(members):
            builder.add_proof(
                r.ReportProofRelation(
                    table=r.ReportTableKey.PLAN_RELATIONS,
                    row=_relation(
                        builder, context, kind=kind, parent=key, ordinal=ordinal, member=member
                    ),
                )
            )


def capture_planning(
    builder: ReportBuilder,
    session: Session,
    authorization: ReportAuthorization,
    *,
    sessions: sessionmaker[Session],
    clock: Callable[[], datetime],
    cursor_signing_key: bytes,
    company: CompanyReportBasis | None = None,
) -> None:
    selection = builder.selection
    if selection.target_version_id is None and selection.plan_revision_id is None:
        return
    authorization.check(session, now=clock())
    service = PostgresPlanningService(
        sessions=sessions, clock=clock, cursor_signing_key=cursor_signing_key
    )
    service._owner_lock(session, authorization.owner_id)
    revision = None
    request = None
    result = None
    plan_input = None
    target_id = selection.target_version_id
    if selection.plan_revision_id is not None:
        row = session.execute(
            select(ContributionPlanResultModel, ContributionPlanRequestModel, ContributionPlanModel)
            .join(
                ContributionPlanRequestModel,
                ContributionPlanRequestModel.id == ContributionPlanResultModel.request_id,
            )
            .join(
                ContributionPlanModel,
                ContributionPlanModel.id == ContributionPlanRequestModel.plan_id,
            )
            .where(
                ContributionPlanResultModel.id == selection.plan_revision_id,
                ContributionPlanResultModel.owner_id == authorization.owner_id,
                ContributionPlanRequestModel.owner_id == authorization.owner_id,
                ContributionPlanModel.owner_id == authorization.owner_id,
                ContributionPlanModel.broker_account_id == authorization.account_id,
                ContributionPlanResultModel.created_at <= selection.source_cutoff_at,
            )
        ).first()
        if row is None:
            raise report_error(app.ReportServiceErrorCode.NOT_FOUND)
        revision, request, _ = row
        if (
            request.snapshot_id != selection.snapshot_id
            or request.reporting_currency != selection.reporting_currency.value
            or (target_id is not None and request.target_version_id != target_id)
        ):
            raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
        target_id = request.target_version_id
        plan_input = service._load_request_input(session, request)
        result = contribution_plan_result_from_json(revision.canonical_result)
        if contribution_plan_result_digest(result) != revision.content_digest:
            raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    version = session.scalar(
        select(TargetVersionModel)
        .join(
            VirtualPortfolioModel,
            VirtualPortfolioModel.id == TargetVersionModel.virtual_portfolio_id,
        )
        .where(
            TargetVersionModel.id == target_id,
            TargetVersionModel.owner_id == authorization.owner_id,
            VirtualPortfolioModel.owner_id == authorization.owner_id,
            VirtualPortfolioModel.broker_account_id == authorization.account_id,
            TargetVersionModel.published_at <= selection.source_cutoff_at,
        )
    )
    if version is None or version.content_digest is None or version.published_at is None:
        raise report_error(app.ReportServiceErrorCode.NOT_FOUND)
    if version.reporting_currency != selection.reporting_currency.value:
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    content = service._targets._content(session, version)
    if (
        t.target_content_digest(
            content,
            reporting_currency=selection.reporting_currency,
            effective_at=version.effective_at,
        )
        != version.content_digest
    ):
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    context = r.ReportContext(
        key="context.target",
        family=r.ReportFamily.TARGET,
        method_key=t.TARGET_VALIDATION_METHOD,
        method_version=version.method_version,
        valuation_at=builder.valuation_at,
        source_cutoff_at=selection.source_cutoff_at,
        source_at=version.effective_at,
        quality=QualityState.FRESH,
        provenance_set_key="sources.target",
        coverage_set_key="coverage.target",
        note_set_key="notes.target",
    )
    builder.add_context(context)
    builder.add_binding(
        r.ReportBinding(
            family=context.family,
            role=r.ReportInputRole.TARGET_VERSION,
            subject_id=version.id,
            parent_id=version.virtual_portfolio_id,
            content_digest=version.content_digest,
            method_key=t.TARGET_VALIDATION_METHOD,
            method_version=version.method_version,
        )
    )
    builder.add_reference(
        r.ReportSourceReference(
            key=f"target.version.{version.id}",
            kind=r.ReportSourceKind.TARGET_VERSION,
            subject_id=version.id,
            parent_id=version.virtual_portfolio_id,
            content_digest=version.content_digest,
            source_at=version.effective_at,
            first_observed_at=version.published_at,
        ),
        provenance_set_key=context.provenance_set_key,
    )
    selected = report_tables(selection)
    nodes = {
        row.key: row
        for row in session.scalars(
            select(TargetNodeModel)
            .where(
                TargetNodeModel.target_version_id == version.id,
                TargetNodeModel.owner_id == authorization.owner_id,
            )
            .order_by(TargetNodeModel.key)
            .limit(257)
        )
    }
    r.report_limit(len(nodes) <= 256, "target_nodes")
    if set(nodes) != {node.key for node in content.nodes}:
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    _target_table(
        builder,
        r.ReportTableKey.TARGET_NODES,
        (
            capture_row(
                builder,
                context,
                r.ReportTableKey.TARGET_NODES,
                key=f"target.node.{node.key}",
                values={
                    "target_version_id": version.id,
                    "node_id": nodes[node.key].id,
                    "parent_node_id": nodes[node.key].parent_id,
                    "node_key": node.key,
                    "node_kind": node.kind,
                    "name": node.name,
                    "ordinal": node.order,
                    "instrument_id": None if node.holding is None else node.holding.instrument_id,
                    "listing_id": None if node.holding is None else node.holding.listing_id,
                    "target_weight": node.weight,
                },
            )
            for node in content.nodes
        ),
    )
    _target_table(
        builder,
        r.ReportTableKey.TARGET_HOLDINGS,
        (
            capture_row(
                builder,
                context,
                r.ReportTableKey.TARGET_HOLDINGS,
                key=f"target.holding.{node.key}",
                values={
                    "node_key": node.key,
                    "state": holding.state,
                    "instrument_id": holding.instrument_id,
                    "listing_id": holding.listing_id,
                    "preferred_listing_id": holding.preferred_listing_id,
                    "identifier_kind": None
                    if holding.requested_identifier is None
                    else holding.requested_identifier.kind,
                    "identifier_value": None
                    if holding.requested_identifier is None
                    else holding.requested_identifier.value,
                    "identifier_provider": None
                    if holding.requested_identifier is None
                    else holding.requested_identifier.provider,
                    "reason": holding.reason,
                },
            )
            for node in content.nodes
            if (holding := node.holding) is not None
        ),
    )
    _target_table(
        builder,
        r.ReportTableKey.TARGET_CONSTRAINTS,
        (
            _constraint_row(builder, context, version.id, constraint)
            for constraint in content.constraints
        ),
    )
    for exclusion in content.exclusions:
        builder.add_proof(
            r.ReportProofRelation(
                table=r.ReportTableKey.TARGET_EXCLUSIONS,
                row=capture_row(
                    builder,
                    context,
                    r.ReportTableKey.TARGET_EXCLUSIONS,
                    key=f"target.exclusion.{exclusion.key}",
                    values=_values(exclusion, r.ReportTableKey.TARGET_EXCLUSIONS),
                ),
            )
        )
    if r.ReportTableKey.DRIFT_ROWS in selected:
        run, calculation, drift_input = service._drift(
            session,
            authorization.owner_id,
            account_id=str(authorization.account_id),
            snapshot_id=str(selection.snapshot_id),
            portfolio_id=str(version.virtual_portfolio_id),
            target_id=str(version.id),
            currency=selection.reporting_currency,
            kind="actual_vs_target",
            basis=d.DriftBasis.DIRECT,
        )
        if company is not None:
            capture_company_actuals(
                builder,
                company,
                drift_input,
                calculation,
                run_id=run.id,
                content_digest=run.content_digest,
            )
        drift_context = _context(builder, calculation.context, key="drift")
        builder.add_binding(
            r.ReportBinding(
                family=drift_context.family,
                role=r.ReportInputRole.CALCULATION,
                subject_id=run.id,
                content_digest=run.content_digest,
                method_key=d.DRIFT_METHOD,
                method_version=d.PLANNING_METHOD_VERSION,
            )
        )
        capture_table(
            builder,
            r.ReportTableKey.DRIFT_ROWS,
            (
                capture_row(
                    builder,
                    drift_context,
                    r.ReportTableKey.DRIFT_ROWS,
                    key=f"drift.row.{row.key}",
                    values=_values(row, r.ReportTableKey.DRIFT_ROWS),
                    currency=selection.reporting_currency,
                )
                for row in calculation.rows
            ),
        )
        _proof_rows(
            builder,
            r.ReportTableKey.DRIFT_TOTALS,
            (
                capture_row(
                    builder,
                    drift_context,
                    r.ReportTableKey.DRIFT_TOTALS,
                    key="drift.totals",
                    values=_values(calculation.totals, r.ReportTableKey.DRIFT_TOTALS),
                    currency=selection.reporting_currency,
                ),
            ),
        )
        for ordinal, key in enumerate(calculation.totals.frontier_keys):
            builder.add_proof(
                r.ReportProofRelation(
                    table=r.ReportTableKey.PLAN_RELATIONS,
                    row=_relation(
                        builder,
                        drift_context,
                        kind="frontier",
                        parent="drift.totals",
                        ordinal=ordinal,
                        member=key,
                    ),
                )
            )
    if (
        result is not None
        and revision is not None
        and request is not None
        and plan_input is not None
    ):
        _capture_plan(builder, result, revision, request, plan_input)
    if (
        r.ReportTableKey.PLAN_RELATIONS in selected
        and r.ReportTableKey.PLAN_RELATIONS not in builder.proof_table_keys
    ):
        capture_table(builder, r.ReportTableKey.PLAN_RELATIONS, ())


def _proof_rows(
    builder: ReportBuilder, table: r.ReportTableKey, rows: Iterable[r.ReportRow]
) -> None:
    for row in rows:
        builder.add_proof(r.ReportProofRelation(table=table, row=row))


def _target_table(
    builder: ReportBuilder, table: r.ReportTableKey, rows: Iterable[r.ReportRow]
) -> None:
    if table in report_tables(builder.selection):
        capture_table(builder, table, rows)
    else:
        _proof_rows(builder, table, rows)


def _constraint_row(
    builder: ReportBuilder,
    context: r.ReportContext,
    version_id: UUID,
    constraint: t.TargetConstraint,
    *,
    table: r.ReportTableKey = r.ReportTableKey.TARGET_CONSTRAINTS,
) -> r.ReportRow:
    return capture_row(
        builder,
        context,
        table,
        key=f"{table.value}.{constraint.key}",
        currency=constraint.currency or builder.selection.reporting_currency,
        values={
            "target_version_id": version_id,
            "key": constraint.key,
            "kind": constraint.kind,
            "node_key": constraint.node_key,
            "amount": constraint.amount,
            "currency": None if constraint.currency is None else constraint.currency.value,
            "weight": constraint.weight,
            "enabled": constraint.enabled,
            "count": constraint.count,
            "coefficient": constraint.coefficient,
        },
    )


def _capture_plan(
    builder: ReportBuilder,
    result: d.ContributionPlanResult,
    revision: ContributionPlanResultModel,
    request: ContributionPlanRequestModel,
    plan_input: d.PlanningInput,
) -> None:
    summary = result.summary
    context = _context(builder, summary.context, key="plan")
    capture_plan_input(
        builder, context, plan_input, request_id=request.id, input_digest=request.input_digest
    )
    currency = builder.selection.reporting_currency
    builder.add_binding(
        r.ReportBinding(
            family=context.family,
            role=r.ReportInputRole.PLAN_REVISION,
            subject_id=revision.id,
            parent_id=request.id,
            content_digest=revision.content_digest,
            method_key=d.PLAN_METHOD,
            method_version=revision.method_version,
        )
    )
    builder.add_binding(
        r.ReportBinding(
            family=context.family,
            role=r.ReportInputRole.INPUT,
            subject_id=request.id,
            content_digest=request.input_digest,
        )
    )
    builder.add_reference(
        r.ReportSourceReference(
            key=f"plan.revision.{revision.id}",
            kind=r.ReportSourceKind.PLAN_REVISION,
            subject_id=revision.id,
            parent_id=request.id,
            content_digest=revision.content_digest,
            source_at=request.source_cutoff_at,
            first_observed_at=revision.created_at,
        ),
        provenance_set_key=context.provenance_set_key,
    )
    values = {
        column.key: cast(ReportValue, getattr(summary, column.key))
        for column in table_schema(r.ReportTableKey.PLAN_SUMMARY).columns
        if column.key != "plan_revision_id"
    }
    values["plan_revision_id"] = revision.id
    capture_table(
        builder,
        r.ReportTableKey.PLAN_SUMMARY,
        (
            capture_row(
                builder,
                context,
                r.ReportTableKey.PLAN_SUMMARY,
                key="plan.summary",
                values=values,
                currency=currency,
            ),
        ),
    )
    capture_table(
        builder,
        r.ReportTableKey.PLAN_LINES,
        (
            capture_row(
                builder,
                context,
                r.ReportTableKey.PLAN_LINES,
                key=f"plan.line.{line.ordinal}",
                values=_values(line, r.ReportTableKey.PLAN_LINES),
                currency=currency,
            )
            for line in result.lines
        ),
    )

    def objectives() -> Iterator[r.ReportRow]:
        for stage in ("objective_before", "objective_after", "lower_bound", "objective_gap"):
            objective = cast(d.PlanObjective | None, getattr(summary, stage))
            if objective is None:
                capture_note(
                    builder,
                    context,
                    key=f"plan.{stage}.unavailable",
                    text=(
                        f"The canonical result has no {stage.replace('_', ' ')} "
                        f"for outcome {summary.outcome.value}."
                    ),
                )
                continue
            for ordinal, score in enumerate(objective.scores):
                yield capture_row(
                    builder,
                    context,
                    r.ReportTableKey.PLAN_OBJECTIVES,
                    key=f"plan.{stage}.{ordinal}",
                    values={
                        "stage": stage,
                        "ordinal": ordinal,
                        "score": score,
                        "quantum": objective.quantum,
                        "rounding": objective.rounding,
                        "rounding_error_bound": objective.rounding_error_bound,
                    },
                )

    capture_table(builder, r.ReportTableKey.PLAN_OBJECTIVES, objectives())

    def relations() -> Iterator[r.ReportRow]:
        for kind, members in (
            ("excluded", summary.excluded_node_keys),
            ("unresolved", summary.unresolved_node_keys),
            ("before_frontier", summary.before_drift.frontier_keys),
            (
                "after_frontier",
                () if summary.after_drift is None else summary.after_drift.frontier_keys,
            ),
        ):
            for ordinal, member in enumerate(members):
                yield _relation(
                    builder,
                    context,
                    kind=kind,
                    parent="plan.summary",
                    ordinal=ordinal,
                    member=member,
                )
        for line in result.lines:
            for ordinal, member in enumerate(line.binding_constraint_keys):
                yield _relation(
                    builder,
                    context,
                    kind="binding_constraint",
                    parent=f"plan.line.{line.ordinal}",
                    ordinal=ordinal,
                    member=member,
                )

    _proof_rows(builder, r.ReportTableKey.PLAN_RELATIONS, relations())
    for ordinal, explanation in enumerate(summary.explanations):
        key = f"plan.explanation.{ordinal}"
        capture_note(
            builder,
            context,
            key=key,
            text=explanation.message,
            code=explanation.code,
            kind=r.ReportNoteKind.WARNING,
        )
        _explanation_members(builder, context, key, explanation)
    for constraint in summary.constraints:
        table = r.ReportTableKey.PLAN_EFFECTIVE_CONSTRAINTS
        row = _constraint_row(builder, context, request.target_version_id, constraint, table=table)
        builder.add_proof(r.ReportProofRelation(table=table, row=row))
    for stage, totals in (("before", summary.before_drift), ("after", summary.after_drift)):
        if totals is not None:
            builder.add_proof(
                r.ReportProofRelation(
                    table=r.ReportTableKey.DRIFT_TOTALS,
                    row=capture_row(
                        builder,
                        context,
                        r.ReportTableKey.DRIFT_TOTALS,
                        key=f"plan.{stage}.drift",
                        values=_values(totals, r.ReportTableKey.DRIFT_TOTALS),
                        currency=currency,
                    ),
                )
            )
