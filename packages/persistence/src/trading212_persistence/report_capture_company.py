"""Explicit company actual copies with original planning bytes and X-ray proof."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.planning_company import project_company_weights
from trading212_application import reports as app
from trading212_application.planning import PlanningServiceError, PlanningServiceErrorCode
from trading212_domain import reports as r
from trading212_domain.errors import fail_validation
from trading212_domain.planning import DriftCalculation, PlanningInput
from trading212_domain.planning_company import PlanningCompanyBasisError, PlanningCompanyProjection
from trading212_domain.report_schema import table_schema
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import SourceUse
from trading212_domain.xray_result import XrayTerminalPath

from .planning_company_store import PlanningCompanyStore, SelectedCompanyBasis
from .report_authorization import ReportAuthorization
from .report_base import report_error
from .report_builder import ReportBuilder
from .report_capture_common import ReportValue, capture_note, capture_row, capture_table
from .report_capture_xray import _metric, capture_xray


@dataclass(frozen=True, slots=True)
class CompanyReportBasis:
    selected: SelectedCompanyBasis
    context: r.ReportContext


def prepare_company_copy(
    builder: ReportBuilder,
    session: Session,
    authorization: ReportAuthorization,
    *,
    sessions: sessionmaker[Session],
    clock: Callable[[], datetime],
    cursor_signing_key: bytes,
    source_use: SourceUse,
) -> CompanyReportBasis | None:
    """Absent pin is a no-op; explicit copies use no latest/create resolver."""
    pin = builder.selection.xray_run_id
    if pin is None:
        return None
    if source_use not in (SourceUse.REPORT, SourceUse.EXPORT):
        fail_validation("A report/export copy permission is required.", field="source_use")
    authorization.check(session, now=clock())
    for namespace in ("sources", "xray"):
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{namespace}:{authorization.owner_id}"},
        )
    service = PlanningCompanyStore(
        sessions=sessions,
        clock=clock,
        cursor_signing_key=cursor_signing_key,
        required_copy_use=source_use,
    )
    try:
        selected = service.load_selected(
            session,
            authorization.as_principal(now=clock()),
            authorization.account_id,
            pin,
            available_by=builder.selection.source_cutoff_at,
        )
    except PlanningServiceError as error:
        code = (
            app.ReportServiceErrorCode.NOT_FOUND
            if error.code is PlanningServiceErrorCode.NOT_FOUND
            else app.ReportServiceErrorCode.ACCESS_DENIED
            if error.code is PlanningServiceErrorCode.ACCESS_DENIED
            else app.ReportServiceErrorCode.REPORT_UNAVAILABLE
        )
        raise report_error(code) from None
    value = selected.value
    if (
        value.account_id,
        value.snapshot_id,
        value.reporting_currency,
        value.valuation_at.value,
    ) != (
        builder.selection.account_id,
        builder.selection.snapshot_id,
        builder.selection.reporting_currency,
        builder.valuation_at,
    ):
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED)
    # Financial source cutoff is checked against the actual captured PlanningInput
    # below; it is distinct from the report's observation/availability cutoff.
    deadline = service._xray_storage_expires_at(
        session, authorization.owner_id, selected.handle.input_id
    )
    if deadline is not None:
        builder.limit_copy_expiry(deadline)
    context = capture_xray(
        builder,
        session,
        authorization,
        sessions=sessions,
        clock=clock,
        cursor_signing_key=cursor_signing_key,
        source_use=source_use,
        selected=selected,
    )
    if context is None:
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    authorization.check(session, now=clock())
    return CompanyReportBasis(selected, context)


def _full_members(
    basis: CompanyReportBasis,
    calculation: DriftCalculation,
    projection: PlanningCompanyProjection,
) -> dict[str, tuple[tuple[UUID, ...], tuple[str, ...]]]:
    """Reconstruct full proof memberships, checking the shared projection digest.

    This only expands retained path/identity references. It performs no identity
    selection or financial arithmetic and never trusts bounded public previews.
    """
    value, result = basis.selected.value, basis.selected.result
    roots = {position.root.key: position.root for position in value.positions}
    holdings = {
        (candidate.id, holding.id): holding
        for candidate in value.constituent_candidates
        for holding in candidate.holdings
    }
    scopes: dict[tuple[UUID, UUID | None], list[XrayTerminalPath]] = {}
    for path in result.terminal_paths:
        if path.fund_edges:
            edge = path.fund_edges[-1]
            if edge.holding_id is None:
                continue
            holding = holdings.get((edge.candidate_id, edge.holding_id))
            if holding is None or holding.instrument_id is None:
                continue
            scope = (holding.instrument_id, holding.listing_id)
        else:
            root = roots.get(path.root_key)
            if root is None:
                continue
            scope = (root.instrument_id, root.listing_id)
        scopes.setdefault(scope, []).append(path)
    rows = {row.key: row for row in calculation.rows}
    result_members: dict[str, tuple[tuple[UUID, ...], tuple[str, ...]]] = {}
    for cell in projection.weights:
        if cell.proof_digest is None:
            continue
        row = rows[cell.row_key]
        if row.instrument_id is None:
            fail_validation("Company row has no retained instrument scope.", field="company")
        scope = (UUID(row.instrument_id), None if row.listing_id is None else UUID(row.listing_id))
        paths = scopes.get(scope, [])
        identities = tuple(
            sorted({item for path in paths for item in path.identity_decision_ids}, key=str)
        )
        keys = tuple(sorted(path.key for path in paths))
        proof = sha256(
            canonical_json((scope, cell.entity_id, identities, keys)).encode()
        ).hexdigest()
        if (
            proof != cell.proof_digest
            or len(identities) != cell.identity_count
            or len(keys) != cell.path_count
        ):
            fail_validation("Company full proof differs from its projection.", field="company")
        result_members[cell.row_key] = identities, keys
    return result_members


def capture_company_actuals(
    builder: ReportBuilder,
    basis: CompanyReportBasis,
    planning: PlanningInput,
    calculation: DriftCalculation,
    *,
    run_id: UUID,
    content_digest: str,
) -> None:
    """Only snapshot actuals; base rows and all hypothetical plan values stay intact."""
    selected = basis.selected
    try:
        projection = project_company_weights(
            planning,
            calculation,
            planning_run_id=run_id,
            planning_content_digest=content_digest,
            xray_run_id=selected.handle.run_id,
            xray_input_id=selected.handle.input_id,
            value=selected.value,
            result=selected.result,
        )
    except PlanningCompanyBasisError:
        raise report_error(app.ReportServiceErrorCode.VALIDATION_FAILED) from None
    binding = projection.binding
    if binding is None or projection.content_digest is None:
        fail_validation("Selected company projection has no binding.", field="company")
    context = basis.context
    capture_note(
        builder,
        context,
        key="company.actual.semantics",
        text=(
            "Full-portfolio company actuals repeat across mapped listings and are non-additive. "
            "Listing targets do not define company drift. "
            "These are snapshot actuals, never post-contribution weights."
        ),
        kind=r.ReportNoteKind.ASSUMPTION,
        code="full_portfolio_company_non_additive",
    )
    table = r.ReportTableKey.PLANNING_COMPANY_BASIS_V1
    capture_table(
        builder,
        table,
        (
            capture_row(
                builder,
                context,
                table,
                key="company.basis",
                values={
                    column.key: projection.content_digest
                    if column.key == "projection_digest"
                    else cast(ReportValue, getattr(binding, column.key))
                    for column in table_schema(table).columns
                },
            ),
        ),
    )
    members = _full_members(basis, calculation, projection)

    def rows() -> Iterator[r.ReportRow]:
        for cell in projection.weights:
            if cell.metric is None:
                unavailable = cell.reason != "company_scope_not_applicable"
                reason = capture_note(
                    builder,
                    context,
                    key=f"company.reason.{cell.reason}",
                    text=cell.reason,
                    code=cell.reason,
                )
                metric = r.ReportCell(
                    kind=r.CellKind.DECIMAL,
                    value=None,
                    decimal_role=r.DecimalRole.RATIO,
                    state=r.CellState.UNAVAILABLE if unavailable else r.CellState.NOT_APPLICABLE,
                    context_key=context.key,
                    reason_key=reason if unavailable else None,
                )
            else:
                metric = _metric(builder, context, f"company.actual.{cell.row_key}", cell.metric)
            parent = f"company.actual.{cell.row_key}"
            for kind, values in zip(
                ("company_identity", "company_path"),
                members.get(cell.row_key, ((), ())),
                strict=True,
            ):
                for ordinal, member in enumerate(values):
                    builder.add_proof(
                        r.ReportProofRelation(
                            table=r.ReportTableKey.PLAN_RELATIONS,
                            row=capture_row(
                                builder,
                                context,
                                r.ReportTableKey.PLAN_RELATIONS,
                                key=f"{parent}.{kind}.{ordinal}",
                                values={
                                    "relation_kind": kind,
                                    "parent_key": parent,
                                    "ordinal": ordinal,
                                    "member_key": str(member),
                                },
                            ),
                        )
                    )
            yield capture_row(
                builder,
                context,
                r.ReportTableKey.PLANNING_COMPANY_ACTUALS_V1,
                key=parent,
                values={
                    "row_key": cell.row_key,
                    "entity_id": cell.entity_id,
                    "actual_weight": metric,
                    "selection_reason": cell.reason,
                    "semantics": cell.semantics,
                    "drift_reason": cell.drift_reason,
                    "identity_count": cell.identity_count,
                    "path_count": cell.path_count,
                    "proof_digest": cell.proof_digest,
                    "projection_digest": projection.content_digest,
                },
            )

    capture_table(builder, r.ReportTableKey.PLANNING_COMPANY_ACTUALS_V1, rows())
