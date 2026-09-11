"""Copy full canonical company buckets onto a separately pinned planning read."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from uuid import UUID

from trading212_domain.planning import DriftCalculation, DriftRow, PlanningInput
from trading212_domain.planning_company import (
    CompanySelectionReason,
    PlanningCompanyBasisError,
    PlanningCompanyBinding,
    PlanningCompanyProjection,
    PlanningCompanyWeight,
)
from trading212_domain.planning_serialization import planning_input_digest
from trading212_domain.serialization import canonical_json
from trading212_domain.xray import (
    XrayDependencyKind,
    XrayDimension,
    XrayInput,
    XrayReason,
    XrayReconciliation,
    XrayReferenceKind,
    XraySubjectKind,
)
from trading212_domain.xray_codec import encode_xray_input, encode_xray_policy
from trading212_domain.xray_result import XrayCalculation, XrayTerminalPath

from .xray import company_exposure_basis


def _digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def unselected_company_projection(rows: tuple[DriftRow, ...]) -> PlanningCompanyProjection:
    return PlanningCompanyProjection(
        None,
        tuple(
            PlanningCompanyWeight(
                row.key,
                None,
                None,
                "company_scope_not_applicable"
                if row.kind in {"cash", "group"}
                else "company_basis_not_selected",
            )
            for row in rows
        ),
        None,
    )


def _reconciliation_inventory(value: XrayReconciliation) -> XrayReconciliation:
    """Compare only provenance tuple order canonically; retain every value and ID."""
    return replace(
        value,
        declared_total=replace(
            value.declared_total,
            source_reference_ids=tuple(sorted(value.declared_total.source_reference_ids, key=str)),
        ),
        root_total=replace(
            value.root_total,
            source_reference_ids=tuple(sorted(value.root_total.source_reference_ids, key=str)),
        ),
        difference=replace(
            value.difference,
            source_reference_ids=tuple(sorted(value.difference.source_reference_ids, key=str)),
        ),
        source_reference_ids=tuple(sorted(value.source_reference_ids, key=str)),
    )


def _validate_basis(
    planning: PlanningInput,
    calculation: DriftCalculation,
    value: XrayInput,
    result: XrayCalculation,
) -> None:
    valuation = planning.valuation
    expected = (
        UUID(valuation.account_id),
        UUID(valuation.snapshot_id),
        valuation.reporting_currency,
        valuation.valuation_at,
        valuation.source_cutoff_at,
    )
    if (
        (
            value.account_id,
            value.snapshot_id,
            value.reporting_currency,
            value.valuation_at.value,
            value.source_cutoff_at.value,
        )
        != expected
        or (
            result.account_id,
            result.snapshot_id,
            result.reporting_currency,
            result.valuation_at.value,
            result.source_cutoff_at.value,
        )
        != expected
        or value.owner_id != result.owner_id
        or sha256(encode_xray_input(value)).hexdigest() != result.input_digest
        or encode_xray_policy(value.policy) != encode_xray_policy(result.policy)
        or calculation.context.input_digest != planning_input_digest(planning)
        or (
            calculation.context.account_id,
            calculation.context.snapshot_id,
            calculation.context.source_cutoff_at,
            calculation.context.as_of,
            calculation.context.reporting_currency,
        )
        != (
            valuation.account_id,
            valuation.snapshot_id,
            valuation.source_cutoff_at,
            valuation.valuation_at,
            valuation.reporting_currency.value,
        )
    ):
        raise PlanningCompanyBasisError("company_pin_mismatch")

    # The two input formats have DIFFERENT snapshot digests. Bind to the saved
    # calculation fingerprint used by the actual X-ray capture producer.
    sources = tuple(source for source in valuation.sources if source.kind == "calculation_run")
    if len(sources) != 1 or value.snapshot_digest != _digest(
        (valuation.snapshot_id, sources[0].content_digest)
    ):
        raise PlanningCompanyBasisError("valuation_basis_mismatch")
    # The calculation dependency hashes its input/output fingerprints; the
    # snapshot dependency hashes the snapshot ID/output fingerprint. Only the
    # latter digest is comparable here. Pair their retained physical identities.
    calculation_id = sources[0].id
    if not any(
        source.kind is XrayDependencyKind.VALUATION
        and source.subject_kind is XraySubjectKind.SOURCE_RECORD
        and str(source.subject_id) == calculation_id
        and source.reference.kind is XrayReferenceKind.CALCULATION_RUN
        and str(source.reference.record_id) == calculation_id
        and source.reference.parent_record_id is None
        for source in value.source_dependencies
    ) or not any(
        source.kind is XrayDependencyKind.VALUATION
        and source.subject_kind is XraySubjectKind.SOURCE_RECORD
        and source.subject_id == value.snapshot_id
        and source.reference.kind is XrayReferenceKind.PORTFOLIO_SNAPSHOT
        and source.reference.record_id == value.snapshot_id
        and str(source.reference.parent_record_id) == calculation_id
        and source.content_digest == value.snapshot_digest
        for source in value.source_dependencies
    ):
        raise PlanningCompanyBasisError("valuation_basis_mismatch")
    # Root scopes and the retained calculation proof bind the valuation. Native
    # broker amounts can differ from reporting amounts after sourced FX.
    planning_positions = {
        (position.instrument_id, position.listing_id) for position in valuation.positions
    }
    xray_positions = {
        (
            str(position.root.instrument_id),
            None if position.root.listing_id is None else str(position.root.listing_id),
        )
        for position in value.positions
    }
    if (
        len(planning_positions) != len(valuation.positions)
        or len(xray_positions) != len(value.positions)
        or planning_positions != xray_positions
        or valuation.portfolio_total != value.portfolio_total.value
        or valuation.coverage_complete != value.valuation_coverage.complete
        or _reconciliation_inventory(result.reconciliation)
        != _reconciliation_inventory(value.reconciliation)
        or value.reconciliation.declared_total.value != valuation.portfolio_total
        or (
            valuation.coverage_complete
            and (
                not valuation.reconciled
                or value.reconciliation.root_total.value != valuation.portfolio_total
                or value.reconciliation.difference.value is None
                or value.reconciliation.difference.value.amount != 0
            )
        )
    ):
        raise PlanningCompanyBasisError("valuation_basis_mismatch")


def project_company_weights(
    planning: PlanningInput,
    calculation: DriftCalculation,
    *,
    planning_run_id: UUID,
    planning_content_digest: str,
    xray_run_id: UUID,
    xray_input_id: UUID,
    value: XrayInput,
    result: XrayCalculation,
) -> PlanningCompanyProjection:
    """Use only retained paths/selected identities; never current catalog mappings.

    No arithmetic derives a new financial scalar. The whole X-ray company
    absolute metric is copied unchanged, including its lower-bound/tiny flags.
    """
    _validate_basis(planning, calculation, value, result)
    if _digest(calculation) != planning_content_digest:
        raise PlanningCompanyBasisError("company_result_invalid")
    basis = company_exposure_basis(result)
    partitions = tuple(row for row in result.dimensions if row.dimension is XrayDimension.COMPANY)
    if len(partitions) != 1 or len(calculation.rows) > 4353:
        raise PlanningCompanyBasisError("company_result_invalid")
    binding = PlanningCompanyBinding(
        planning_run_id=planning_run_id,
        planning_input_digest=calculation.context.input_digest,
        planning_content_digest=planning_content_digest,
        valuation_digest=planning.valuation.content_digest,
        xray_run_id=xray_run_id,
        xray_input_id=xray_input_id,
        xray_input_digest=basis.input_digest,
        xray_content_digest=basis.result_digest,
        account_id=value.account_id,
        snapshot_id=value.snapshot_id,
        reporting_currency=value.reporting_currency.value,
        valuation_at=value.valuation_at.value,
        source_cutoff_at=value.source_cutoff_at.value,
        policy_id=value.policy.id,
        policy_digest=sha256(encode_xray_policy(value.policy)).hexdigest(),
        total=basis.total,
        company_partition=partitions[0],
    )
    buckets = {bucket.bucket_key: bucket for bucket in basis.exposures}
    if len(buckets) != len(basis.exposures):
        raise PlanningCompanyBasisError("company_result_invalid")
    roots = {position.root.key: position.root for position in value.positions}
    holdings = {
        (candidate.id, holding.id): holding
        for candidate in value.constituent_candidates
        for holding in candidate.holdings
    }
    funds = {
        position.root.instrument_id for position in result.direct_positions if position.is_fund
    }
    funds.update(row.instrument_id for row in result.held_funds)
    selected: dict[tuple[UUID, UUID | None], list[XrayTerminalPath]] = {}
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
        selected.setdefault(scope, []).append(path)

    # Memoize by exact instrument/listing scope. Avoid repeatedly serializing
    # full source memberships for repeated listings/company cells.
    scopes: dict[tuple[UUID, UUID | None], PlanningCompanyWeight] = {}
    metric_digests: dict[str, str] = {}
    weights: list[PlanningCompanyWeight] = []
    semantic_rows: list[tuple[str, str]] = []
    for row in calculation.rows:
        if row.kind in {"group", "cash"} or (
            row.instrument_id is not None and UUID(row.instrument_id) in funds
        ):
            cell = PlanningCompanyWeight(row.key, None, None, "company_scope_not_applicable")
        elif row.instrument_id is None:
            cell = PlanningCompanyWeight(row.key, None, None, "company_identity_unavailable")
        else:
            scope = (
                UUID(row.instrument_id),
                None if row.listing_id is None else UUID(row.listing_id),
            )
            template = scopes.get(scope)
            if template is None:
                paths = tuple(selected.get(scope, ()))
                entities = {path.entity_id for path in paths}
                reason: CompanySelectionReason | None = (
                    "company_identity_conflict"
                    if any(
                        path.unresolved_reason is XrayReason.AMBIGUOUS_IDENTITY for path in paths
                    )
                    else "company_identity_unavailable"
                    if not paths or entities == {None}
                    else "company_identity_conflict"
                    if None in entities or len(entities) != 1
                    else None
                )
                if reason is not None:
                    template = PlanningCompanyWeight("", None, None, reason)
                else:
                    entity = next(iter(entities))
                    assert entity is not None
                    bucket = buckets.get(str(entity))
                    metric = None if bucket is None else bucket.absolute_weight
                    decisions = tuple(
                        sorted(
                            {item for path in paths for item in path.identity_decision_ids}, key=str
                        )
                    )
                    keys = tuple(sorted(path.key for path in paths))
                    proof = _digest((scope, entity, decisions, keys))
                    template = PlanningCompanyWeight(
                        "",
                        entity,
                        metric,
                        "company_bucket_unavailable"
                        if metric is None
                        else "company_metric_unavailable"
                        if metric.value is None
                        else "available",
                        decisions[:64],
                        len(decisions),
                        max(0, len(decisions) - 64),
                        keys[:64],
                        len(keys),
                        max(0, len(keys) - 64),
                        proof,
                    )
                scopes[scope] = template
            cell = replace(template, row_key=row.key)
        weights.append(cell)
        # Input/result digests already bind the full immutable universe. Include
        # each complete metric's digest, rather than N copies of its source list.
        metric_key = str(cell.entity_id)
        if cell.metric is not None and metric_key not in metric_digests:
            metric_digests[metric_key] = _digest(cell.metric)
        semantic_rows.append(
            (
                row.key,
                _digest(
                    (
                        cell.entity_id,
                        cell.reason,
                        cell.proof_digest,
                        None if cell.metric is None else metric_digests[metric_key],
                    )
                ),
            )
        )
    return PlanningCompanyProjection(
        binding,
        tuple(weights),
        _digest((binding, tuple(sorted(semantic_rows)))),
    )
