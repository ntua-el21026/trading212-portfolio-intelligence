"""Fixed-schema normalized planning projection writers and integrity checks."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application.planning_jobs import PlanJobFailureCode, PlanJobInputError
from trading212_domain import planning as d
from trading212_domain.planning_serialization import (
    contribution_plan_result_digest,
    planning_input_digest,
)
from trading212_domain.serialization import canonical_json

from .models import PortfolioSnapshotModel
from .planning_inputs import digest
from .planning_models import (
    AnalyticsDriftRowModel,
    AnalyticsRunModel,
    AnalyticsSourceModel,
    ContributionPlanCatalogModel,
    ContributionPlanConstraintModel,
    ContributionPlanExplanationModel,
    ContributionPlanHoldingConstraintModel,
    ContributionPlanInputModel,
    ContributionPlanLineModel,
    ContributionPlanModel,
    ContributionPlanRequestModel,
    ContributionPlanResultModel,
    ContributionPlanSelectionModel,
    ContributionPlanSourceModel,
    PlanningOwned,
)


def _uuid(value: str | None) -> UUID | None:
    return None if value is None else UUID(value)


def _input_rows(value: d.PlanningInput) -> dict[type[PlanningOwned], list[dict[str, object]]]:
    identities = {x.id: x for x in value.node_identities}
    holdings = {x.holding_id: x for x in value.node_identities if x.holding_id is not None}
    rows: dict[type[PlanningOwned], list[dict[str, object]]] = {
        m: []
        for m in (
            ContributionPlanInputModel,
            ContributionPlanCatalogModel,
            ContributionPlanConstraintModel,
            ContributionPlanSelectionModel,
            ContributionPlanHoldingConstraintModel,
            ContributionPlanSourceModel,
        )
    }
    components: tuple[d.ValuationPosition | d.ValuationCash, ...] = (
        *value.valuation.positions,
        *value.valuation.cash_components,
    )
    for ordinal, item in enumerate(components):
        fx = item.fx
        rows[ContributionPlanInputModel].append(
            {
                "ordinal": ordinal,
                "kind": "position" if isinstance(item, d.ValuationPosition) else "cash",
                "listing_id": UUID(item.listing_id)
                if isinstance(item, d.ValuationPosition)
                else None,
                "instrument_id": _uuid(item.instrument_id)
                if isinstance(item, d.ValuationPosition)
                else None,
                "amount": None if item.value is None else item.value.amount,
                "currency": value.valuation.reporting_currency.value
                if item.value is None
                else item.value.currency.value,
                "quality_state": item.quality.value,
                "fx_source_id": None if fx is None else UUID(fx.source.id),
                "fx_digest": None if fx is None else fx.source.content_digest,
                "fx_base_currency": None if fx is None else fx.base.value,
                "fx_quote_currency": None if fx is None else fx.quote.value,
                "fx_rate": None if fx is None else fx.rate,
                "fx_effective_at": None if fx is None else fx.source.effective_at,
                "fx_first_observed_at": None if fx is None else fx.source.first_observed_at,
            }
        )
    rows[ContributionPlanCatalogModel] = [
        {"listing_id": x.listing_id, "instrument_id": x.instrument_id, "active": x.eligible}
        for x in value.catalog.listings
    ]
    for c in value.options.allocation_constraints:
        rows[ContributionPlanConstraintModel].append(
            {
                "key": c.key,
                "kind": c.kind.value,
                "node_key": None if c.node_id is None else identities[c.node_id].key,
                "amount": c.amount,
                "currency": None if c.currency is None else c.currency.value,
                "weight": c.weight,
                "enabled": c.enabled,
                "line_count": c.count,
                "coefficient": c.coefficient,
            }
        )
    for kind, selected in (
        ("eligible", value.options.eligible_holding_ids or ()),
        ("excluded", value.options.excluded_holding_ids),
        ("restricted", value.options.restricted_group_ids),
    ):
        for identity in selected:
            node = identities[identity] if kind == "restricted" else holdings[identity]
            rows[ContributionPlanSelectionModel].append(
                {
                    "kind": kind,
                    "target_node_id": UUID(node.id),
                    "holding_id": _uuid(node.holding_id),
                    "listing_id": None,
                }
            )
    for preference in value.options.listing_preferences:
        node = holdings[preference.holding_id]
        rows[ContributionPlanSelectionModel].append(
            {
                "kind": "preference",
                "target_node_id": UUID(node.id),
                "holding_id": UUID(preference.holding_id),
                "listing_id": UUID(preference.listing_id),
            }
        )
    for c2 in value.options.holding_constraints:
        rows[ContributionPlanHoldingConstraintModel].append(
            {
                "holding_id": UUID(c2.holding_id),
                "minimum_amount": c2.minimum_amount,
                "value_increment": c2.value_increment,
                "maximum_post_weight": c2.maximum_post_weight,
            }
        )
    sources = (
        *value.valuation.sources,
        d.PlanningSource(
            "target_version",
            value.target_version_id,
            value.target_content_digest,
            "1",
            value.target_effective_at,
            value.target_published_at,
        ),
    )
    # Two provenance roles may reference the same minimized source record. Preserve
    # their exact kinds in the canonical input; the normalized economic FK is unique.
    unique = {}
    for source in sources:
        kind = {
            "portfolio_snapshot": "snapshot",
            "calculation_run": "calculation",
            "target_version": "target",
            "provider_observation": "source_record",
            "provider_fx_observation": "source_record",
        }[source.kind]
        column = {
            "snapshot": "snapshot_id",
            "calculation": "calculation_run_id",
            "target": "target_version_id",
            "source_record": "source_record_id",
        }[kind]
        fields = {
            "kind": kind,
            "source_id": UUID(source.id),
            "snapshot_id": None,
            "calculation_run_id": None,
            "target_version_id": None,
            "source_record_id": None,
            "target_mapping_id": None,
            "digest": source.content_digest,
            "effective_at": source.effective_at,
            "first_observed_at": source.first_observed_at,
        }
        fields[column] = UUID(source.id)
        unique[(kind, source.id)] = fields
    rows[ContributionPlanSourceModel] = list(unique.values())
    return rows


def _normalized_digest(rows: dict[type[PlanningOwned], list[dict[str, object]]]) -> str:
    return digest({m.__tablename__: sorted(items, key=canonical_json) for m, items in rows.items()})


def persist_input(
    session: Session,
    plan: ContributionPlanModel,
    value: d.PlanningInput,
    *,
    command_digest: str,
    actor: str,
    correlation: str,
    at: datetime,
) -> ContributionPlanRequestModel:
    snapshot = session.get(PortfolioSnapshotModel, UUID(value.valuation.snapshot_id))
    if snapshot is None:
        raise PlanJobInputError(PlanJobFailureCode.INPUT_UNAVAILABLE)
    rows = _input_rows(value)
    request = ContributionPlanRequestModel(
        id=uuid4(),
        owner_id=plan.owner_id,
        plan_id=plan.id,
        revision_number=plan.revision,
        target_version_id=UUID(value.target_version_id),
        snapshot_id=snapshot.id,
        calculation_run_id=snapshot.calculation_run_id,
        contribution=value.options.contribution.amount,
        reporting_currency=value.valuation.reporting_currency.value,
        mode=value.options.mode.value,
        coverage_policy=value.options.coverage_policy.value,
        monetary_quantum=value.options.monetary_quantum,
        currency_policy_version=value.currency_policy_version,
        method_version=value.method_version,
        schema_version=value.schema_version,
        target_content_digest=value.target_content_digest,
        valuation_content_digest=value.valuation.content_digest,
        input_digest=planning_input_digest(value),
        command_digest=command_digest,
        valuation_at=value.valuation.valuation_at,
        source_cutoff_at=value.valuation.source_cutoff_at,
        portfolio_total=None
        if value.valuation.portfolio_total is None
        else value.valuation.portfolio_total.amount,
        quality_state=value.valuation.quality.value,
        coverage_complete=value.valuation.coverage_complete,
        reconciled=value.valuation.reconciled,
        missing_inputs=list(value.valuation.missing_inputs),
        cash_reserve=value.options.cash_reserve,
        actor_principal_id=actor,
        correlation_id=correlation,
        canonical_input=canonical_json(value).encode(),
        normalized_digest=_normalized_digest(rows),
        created_at=at,
    )
    session.add(request)
    session.flush()
    for model, items in rows.items():
        for fields in items:
            session.add(
                model(owner_id=plan.owner_id, request_id=request.id, created_at=at, **fields)
            )
    session.flush()
    return request


def verify_normalized_input(
    session: Session, request: ContributionPlanRequestModel, value: d.PlanningInput
) -> None:
    expected = _input_rows(value)
    observed: dict[type[PlanningOwned], list[dict[str, object]]] = {}
    for model in expected:
        fields = set(model.__table__.columns.keys()) - {
            "id",
            "created_at",
            "owner_id",
            "request_id",
        }
        records = list(
            session.scalars(select(model).where(model.__table__.c.request_id == request.id))
        )
        observed[model] = [{key: getattr(r, key) for key in fields} for r in records]
        if any(r.owner_id != request.owner_id for r in records):
            raise PlanJobInputError(PlanJobFailureCode.ACCESS_DENIED)
    if (
        _normalized_digest(observed) != request.normalized_digest
        or _normalized_digest(expected) != request.normalized_digest
    ):
        raise PlanJobInputError(PlanJobFailureCode.INPUT_CHANGED)
    if (
        request.target_version_id != UUID(value.target_version_id)
        or request.snapshot_id != UUID(value.valuation.snapshot_id)
        or request.contribution != value.options.contribution.amount
        or request.monetary_quantum != value.options.monetary_quantum
        or request.reporting_currency != value.valuation.reporting_currency.value
    ):
        raise PlanJobInputError(PlanJobFailureCode.INPUT_CHANGED)


def persist_result(
    session: Session,
    request: ContributionPlanRequestModel,
    value: d.ContributionPlanResult,
    *,
    at: datetime,
) -> ContributionPlanResultModel:
    summary = value.summary
    result = ContributionPlanResultModel(
        id=uuid4(),
        owner_id=request.owner_id,
        request_id=request.id,
        outcome=summary.outcome.value,
        method_version=summary.context.method_version,
        content_digest=contribution_plan_result_digest(value),
        residual_cash=None if summary.residual_cash is None else summary.residual_cash.amount,
        reporting_currency=request.reporting_currency,
        objective_before=[]
        if summary.objective_before is None
        else list(summary.objective_before.scores),
        objective_after=[]
        if summary.objective_after is None
        else list(summary.objective_after.scores),
        lower_bound=[] if summary.lower_bound is None else list(summary.lower_bound.scores),
        objective_gap=[] if summary.objective_gap is None else list(summary.objective_gap.scores),
        search_nodes=summary.attempted_assignments,
        canonical_result=canonical_json(value).encode(),
        created_at=at,
    )
    session.add(result)
    session.flush()
    for line in value.lines:
        session.add(
            ContributionPlanLineModel(
                owner_id=request.owner_id,
                result_id=result.id,
                ordinal=line.ordinal,
                node_key=line.node_key,
                target_node_id=UUID(line.node_id),
                holding_id=UUID(line.holding_id),
                instrument_id=_uuid(line.instrument_id),
                listing_id=_uuid(line.listing_id),
                current_value=line.current_value.amount,
                current_weight=line.current_weight,
                target_weight=line.target_weight,
                post_value=line.post_value.amount,
                post_weight=line.post_weight,
                recommended_amount=line.recommended_amount.amount,
                currency=line.recommended_amount.currency.value,
                minimum_funded_amount=line.minimum_funded_amount.amount,
                value_increment=line.value_increment.amount,
                excluded=line.excluded,
                binding_constraint_keys=list(line.binding_constraint_keys),
                created_at=at,
            )
        )
    for ordinal, explanation in enumerate(summary.explanations):
        session.add(
            ContributionPlanExplanationModel(
                owner_id=request.owner_id,
                result_id=result.id,
                ordinal=ordinal,
                code=explanation.code,
                constraint_keys=list(explanation.constraint_keys),
                node_keys=list(explanation.node_keys),
                message=explanation.message,
                severity=explanation.severity,
                created_at=at,
            )
        )
    session.flush()
    return result


def persist_drift(
    session: Session,
    owner: UUID,
    value: d.PlanningInput,
    calculation: d.DriftCalculation,
    *,
    kind: str,
    input_digest: str,
    at: datetime,
) -> AnalyticsRunModel:
    run = AnalyticsRunModel(
        id=uuid4(),
        owner_id=owner,
        broker_account_id=UUID(value.valuation.account_id),
        kind=kind,
        input_digest=input_digest,
        content_digest=digest(calculation),
        canonical_input=canonical_json(value).encode(),
        method_version=calculation.context.method_version,
        reporting_currency=value.valuation.reporting_currency.value,
        valuation_at=value.valuation.valuation_at,
        source_cutoff_at=value.valuation.source_cutoff_at,
        canonical_result=canonical_json(calculation).encode(),
        created_at=at,
    )
    session.add(run)
    session.flush()
    session.add_all(
        (
            AnalyticsSourceModel(
                owner_id=owner,
                run_id=run.id,
                snapshot_id=UUID(value.valuation.snapshot_id),
                digest=value.valuation.content_digest,
                created_at=at,
            ),
            AnalyticsSourceModel(
                owner_id=owner,
                run_id=run.id,
                target_version_id=UUID(value.target_version_id),
                digest=value.target_content_digest,
                created_at=at,
            ),
        )
    )
    records = {
        s.id: s
        for s in value.valuation.sources
        if s.kind in {"provider_observation", "provider_fx_observation"}
    }
    for source in records.values():
        session.add(
            AnalyticsSourceModel(
                owner_id=owner,
                run_id=run.id,
                source_record_id=UUID(source.id),
                digest=source.content_digest,
                created_at=at,
            )
        )
    session.flush()
    for ordinal, row in enumerate(calculation.rows):
        session.add(
            AnalyticsDriftRowModel(
                owner_id=owner,
                run_id=run.id,
                ordinal=ordinal,
                key=row.key,
                node_id=_uuid(row.node_id),
                holding_id=_uuid(row.holding_id),
                kind=row.kind,
                parent_key=row.parent_key,
                name=row.name,
                depth=row.depth,
                listing_id=_uuid(row.listing_id),
                instrument_id=_uuid(row.instrument_id),
                target_weight=row.target_weight,
                actual_value=None if row.actual_value is None else row.actual_value.amount,
                currency=value.valuation.reporting_currency.value,
                actual_direct_weight=row.actual_direct_weight,
                effective_weight=row.effective_weight,
                effective_weight_reason=row.effective_weight_reason,
                signed_drift=row.signed_drift,
                absolute_drift=row.absolute_drift,
                relative_drift=row.relative_drift,
                relative_drift_reason=row.relative_drift_reason,
                classification=row.classification,
                monetary_gap=None if row.monetary_gap is None else row.monetary_gap.amount,
                quality_state=row.quality.value,
                created_at=at,
            )
        )
    session.flush()
    return run
