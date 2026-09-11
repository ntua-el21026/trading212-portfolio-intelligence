"""Synthetic inputs for actual canonical producers; no stored result fabrication."""

from dataclasses import replace
from hashlib import sha256
from uuid import UUID

from trading212_analytics.planning import calculate_drift, validate_planning_input
from trading212_analytics.planning_company import project_company_weights
from trading212_analytics.xray import calculate_xray
from trading212_domain import xray as d
from trading212_domain.planning import PlanningInput, PlanningSource
from trading212_domain.planning_company import PlanningCompanyProjection
from trading212_domain.serialization import canonical_json
from trading212_domain.targets import target_content_digest
from trading212_domain.xray_result import XrayCalculation

from .planning_factories import planning_input
from .xray_factories import Builder, uid


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def company_inputs(
    *, tiny: bool = False, identity: str = "resolved"
) -> tuple[PlanningInput, d.XrayInput]:
    amounts = ("0.000000000000000001", "0", "500", "300") if tiny else ("100", "100", "500", "300")
    planning = planning_input(amounts, ("0.1", "0.1", "0.5", "0.3"), grouped=True)
    builder = Builder()
    for i, amount in enumerate(amounts):
        builder.position(uid(100 + i), amount, listing=uid(200 + i))
    if identity != "missing":
        for instrument in (100, 101):
            builder.identity(uid(instrument), uid(110))
            if identity == "conflict":
                builder.identity(uid(instrument), uid(120))
    builder.identity(uid(111), uid(120))
    builder.classifications_for(uid(110), key="alpha")
    builder.classifications_for(uid(120), key="beta")
    builder.fund(uid(102), ((uid(111), "1"),) if tiny else ((uid(100), "0.6"), (uid(111), "0.3")))
    builder.fund(uid(103), ((uid(111), "1"),) if tiny else ((uid(100), "0.2"), (uid(111), "0.8")))
    value = builder.finish()
    # Company planning consumes the same as-of valuation, without later source knowledge.
    value = replace(value, source_cutoff_at=value.valuation_at)
    fingerprint = "c" * 64
    snapshot_digest = digest((str(value.snapshot_id), fingerprint))
    calculation_reference = d.XraySourceDependency(
        uid(9002),
        value.owner_id,
        value.account_id,
        value.snapshot_id,
        d.XrayDependencyKind.VALUATION,
        d.XraySubjectKind.SOURCE_RECORD,
        uid(9001),
        None,
        None,
        digest(("b" * 64, fingerprint)),
        d.XrayPhysicalReference(d.XrayReferenceKind.CALCULATION_RUN, uid(9001), None),
    )
    snapshot_reference = d.XraySourceDependency(
        uid(9003),
        value.owner_id,
        value.account_id,
        value.snapshot_id,
        d.XrayDependencyKind.VALUATION,
        d.XraySubjectKind.SOURCE_RECORD,
        value.snapshot_id,
        None,
        None,
        snapshot_digest,
        d.XrayPhysicalReference(
            d.XrayReferenceKind.PORTFOLIO_SNAPSHOT, value.snapshot_id, uid(9001)
        ),
    )
    value = replace(
        value,
        snapshot_digest=snapshot_digest,
        source_dependencies=(
            *value.source_dependencies,
            calculation_reference,
            snapshot_reference,
        ),
        positions=tuple(
            replace(row, valuation_refs=(*row.valuation_refs, calculation_reference.id))
            for row in value.positions
        ),
    )
    valuation = replace(
        planning.valuation,
        snapshot_id=str(value.snapshot_id),
        valuation_at=value.valuation_at.value,
        source_cutoff_at=value.source_cutoff_at.value,
        sources=(
            PlanningSource(
                "portfolio_snapshot",
                str(value.snapshot_id),
                "a" * 64,
                "1",
                value.valuation_at.value,
                value.source_cutoff_at.value,
            ),
            PlanningSource(
                "calculation_run",
                str(uid(9001)),
                fingerprint,
                "1",
                value.valuation_at.value,
                value.source_cutoff_at.value,
            ),
        ),
    )
    planning = replace(
        planning,
        valuation=valuation,
        target_effective_at=value.valuation_at.value,
        target_published_at=value.valuation_at.value,
        target_content_digest=target_content_digest(
            planning.target_content,
            reporting_currency=value.reporting_currency,
            effective_at=value.valuation_at.value,
        ),
    )
    # Match persistence capture, including the canonical currency quantum.
    return validate_planning_input(planning), value


def project(
    planning: PlanningInput,
    value: d.XrayInput,
    result: XrayCalculation | None = None,
    *,
    run: int = 9101,
) -> PlanningCompanyProjection:
    calculation = calculate_drift(planning)
    return project_company_weights(
        planning,
        calculation,
        planning_run_id=UUID(int=9100),
        planning_content_digest=digest(calculation),
        xray_run_id=UUID(int=run),
        xray_input_id=UUID(int=9102),
        value=value,
        result=calculate_xray(value) if result is None else result,
    )
