"""Constructor and codec admission for the closed X-ray schema."""

from __future__ import annotations

import re
from dataclasses import fields
from decimal import (
    ROUND_HALF_EVEN,
    Clamped,
    Context,
    Decimal,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
)
from enum import Enum
from types import UnionType
from typing import Annotated, Any, Literal, NoReturn, Union, get_args, get_origin, get_type_hints
from uuid import UUID

from trading212_domain.errors import DomainError, ErrorCode, fail_validation
from trading212_domain.values import CurrencyCode, Instant, Money

ZERO = Decimal("0")
ONE = Decimal("1")
_ROLES = {
    "root_coefficient": (Decimal("1e38"), False, False),
    "relative_coefficient": (Decimal("1e72"), True, False),
    "path_coefficient": (Decimal("1e110"), False, False),
    "aggregate_coefficient": (Decimal("1e114"), False, False),
    "square_coefficient": (Decimal("1e228"), False, False),
    "hhi_coefficient": (Decimal("1e232"), False, False),
    "residual_coefficient": (Decimal("1e43"), False, True),
}
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ROOT = re.compile(r"(?:position|cash):[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")


def invalid(field: str = "xray") -> NoReturn:
    fail_validation("Invalid closed X-ray value or invariant.", field=field)


def bound(condition: bool, field: str) -> None:
    if not condition:
        raise DomainError(ErrorCode.INPUT_BOUND_EXCEEDED, "X-ray input bound exceeded.", field)


def decimal_role(value: object, role: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        invalid(role)
    assert isinstance(value, Decimal)
    shape = value.as_tuple()
    exponent = shape.exponent
    if not isinstance(exponent, int):
        invalid(role)
    assert isinstance(exponent, int)
    if role in ("amount", "weight"):
        if not -18 <= exponent <= 20 or len(shape.digits) > 38:
            invalid(role)
        if value.copy_abs() >= Decimal("1e20"):
            invalid(role)
        if role == "weight" and not ZERO <= value <= ONE:
            invalid(role)
    else:
        if role not in _ROLES or not 0 <= exponent <= 249 or len(shape.digits) > 250:
            invalid(role)
        maximum, inclusive, signed = _ROLES[role]
        magnitude = value.copy_abs()
        if (not signed and value < ZERO) or magnitude > maximum:
            invalid(role)
        if not inclusive and magnitude == maximum:
            invalid(role)
    return ZERO if value.is_zero() else value


_HINT_CACHE: dict[type[object], dict[str, Any]] = {}


def hints(kind: type[object]) -> dict[str, Any]:
    # Only fixed dataclass metadata is cached, never captured or provider data.
    # Keep the cache bounded even if a new internal caller passes additional types.
    cached = _HINT_CACHE.get(kind)
    if cached is None:
        cached = get_type_hints(kind, include_extras=True)
        if len(_HINT_CACHE) >= 128:
            _HINT_CACHE.clear()
        _HINT_CACHE[kind] = cached
    return cached


def checked(value: object, annotation: Any, field: str) -> object:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is Annotated:
        return decimal_role(value, arguments[1])
    if origin in (UnionType, Union):
        for option in arguments:
            if value is None and option is type(None):
                return None
            base = get_args(option)[0] if get_origin(option) is Annotated else option
            if isinstance(base, type) and type(value) is base:
                return checked(value, option, field)
        invalid(field)
    if origin is Literal:
        if not any(type(value) is type(item) and value == item for item in arguments):
            invalid(field)
        return value
    if origin is tuple:
        if type(value) is not tuple:
            invalid(field)
        assert isinstance(value, tuple)
        bound(len(value) <= 100_000, field)
        for item in value:
            checked(item, arguments[0], field)
        return value
    if annotation is str:
        if type(value) is not str:
            invalid(field)
        assert isinstance(value, str)
        if not value or len(value) > 1024 or any(ord(char) < 32 for char in value):
            invalid(field)
    elif annotation is int:
        if type(value) is not int or not 0 <= value <= 2_147_483_647:
            invalid(field)
    elif annotation is bool:
        if type(value) is not bool:
            invalid(field)
    elif annotation is UUID:
        if type(value) is not UUID:
            invalid(field)
    elif isinstance(annotation, type) and issubclass(annotation, Enum):
        if type(value) is not annotation:
            invalid(field)
    elif annotation in (Money, CurrencyCode, Instant):
        if type(value) is not annotation:
            invalid(field)
        if isinstance(value, Money):
            decimal_role(value.amount, "amount")
    elif isinstance(annotation, type):
        if type(value) is not annotation:
            invalid(field)
    else:
        invalid(field)
    return value


def _unique(values: tuple[object, ...], field: str) -> None:
    if len(set(values)) != len(values):
        invalid(field)


def validate_record(record: Any) -> None:
    for item in fields(record):
        value = getattr(record, item.name)
        result = checked(value, hints(type(record))[item.name], item.name)
        if result is not value:
            object.__setattr__(record, item.name, result)
        if item.name.endswith("digest") and not _DIGEST.fullmatch(value):
            invalid(item.name)
        if item.name in ("root_key", "composition_root_key") and not _ROOT.fullmatch(value):
            invalid(item.name)
    name = type(record).__name__
    if name in ("XrayMoneyMetric", "XrayRatioMetric"):
        from trading212_domain.xray import XrayAvailability

        if (record.value is None) != (record.availability is XrayAvailability.UNAVAILABLE):
            invalid("metric.availability")
        if (record.value is None) != (record.reason is not None):
            invalid("metric.availability")
        if name == "XrayMoneyMetric":
            from trading212_domain.enums import ValueOrigin

            if (record.value is None) != (record.origin is ValueOrigin.UNAVAILABLE):
                invalid("metric.origin")
        elif record.positive_below_quantum and record.value != ZERO:
            invalid("metric.positive_below_quantum")
    elif name == "XrayReconciliation":
        known = record.declared_total.value is not None and record.root_total.value is not None
        if (record.difference.value is not None) != known:
            invalid("reconciliation.availability")
    elif name == "XraySourceDependency":
        _dependency_shape(record)
    elif name == "XrayPhysicalReference":
        from trading212_domain.xray import XrayReferenceKind as K

        if (
            record.kind
            in (
                K.SNAPSHOT_POSITION,
                K.SNAPSHOT_CASH,
                K.BROKER_SOURCE_RECORD,
                K.RECONCILIATION_DISCREPANCY,
                K.PRICE_OBSERVATION,
                K.FX_OBSERVATION,
                K.FX_COVERAGE_GAP,
                K.FUND_MAPPING,
                K.CONSTITUENT_SNAPSHOT,
                K.CONSTITUENT_HOLDING,
                K.ENTITY_EVIDENCE_REFERENCE,
                K.RELATIONSHIP,
                K.CLASSIFICATION_ASSIGNMENT,
            )
            and record.parent_record_id is None
        ):
            invalid("reference.parent")
    elif name == "XrayBrokerFx":
        if record.rate <= ZERO or record.observed_at > record.source_observed_at:
            invalid("broker_fx.quote")
        if record.base_currency == record.quote_currency and record.rate != ONE:
            invalid("broker_fx.direction")
        bound(len(record.source) <= 120, "broker_fx.source")
    elif name == "XrayFxLeg":
        from trading212_domain.sources import ObservationState

        if (record.observation_id is None) == (record.coverage_gap_id is None):
            invalid("licensed_fx.record_identity")
        if record.coverage_gap_id is not None and record.state is not ObservationState.MISSING:
            invalid("licensed_fx.coverage_gap_state")
        if (record.rate is not None) != (record.state is ObservationState.AVAILABLE):
            invalid("licensed_fx.availability")
        if (
            record.rate is not None and record.rate <= ZERO
        ) or record.base_currency == record.quote_currency:
            invalid("licensed_fx.quote")
    elif name == "XrayLicensedFx":
        if record.consumer_key != "portfolio_total" and not _ROOT.fullmatch(record.consumer_key):
            invalid("licensed_fx.consumer")
        bound(len(record.legs) <= 2, "licensed_fx.legs")
        _unique(tuple(item.source_reference_id for item in record.legs), "licensed_fx.references")
        if len({(leg.snapshot_id, leg.observed_at) for leg in record.legs}) > 1:
            invalid("licensed_fx.common_fixing")
        if record.input_value.value is None:
            invalid("licensed_fx.input_value")
        current = record.input_value.value.currency
        if current == record.output_currency:
            invalid("licensed_fx.identity")
        visited = {current}
        for leg in record.legs:
            base, quote = (
                (leg.base_currency, leg.quote_currency)
                if leg.operation == "multiply"
                else (leg.quote_currency, leg.base_currency)
            )
            if current != base or quote in visited:
                invalid("licensed_fx.direction")
            current = quote
            visited.add(current)
        if record.legs and current != record.output_currency:
            invalid("licensed_fx.output_currency")
    elif name == "XrayWarning":
        bound(
            len(record.source_reference_ids) <= 256 and len(record.path_keys) <= 256,
            "warning.references",
        )
    elif name == "XrayEvidence":
        if record.valid_until is not None and record.valid_until <= record.effective_at:
            invalid("evidence.interval")
    elif name == "XrayProviderSelectionPolicy":
        bound(0 < len(record.provider_order) <= 256, "provider_order")
        _unique(record.provider_order, "provider_order")
        for provider in record.provider_order:
            canonical_provider(provider)
    elif name == "XrayPolicyVersion":
        from trading212_domain.xray import XrayDimension

        if {item.dimension for item in record.taxonomy_versions} != set(XrayDimension) - {
            XrayDimension.COMPANY
        } or len(record.taxonomy_versions) != 5:
            invalid("taxonomy_versions")
    elif name == "XrayConstituentHolding":
        from trading212_domain.xray import XrayHoldingKind

        if (record.kind is XrayHoldingKind.INSTRUMENT) != (record.instrument_id is not None):
            invalid("holding.instrument")
        if record.kind is XrayHoldingKind.ENTITY and record.entity_id is None:
            invalid("holding.entity")
        if (
            record.kind in (XrayHoldingKind.CASH, XrayHoldingKind.UNRESOLVED)
            and record.entity_id is not None
        ):
            invalid("holding.entity")
        if (
            record.kind in (XrayHoldingKind.INSTRUMENT, XrayHoldingKind.ENTITY)
            and record.evidence_key is None
        ):
            invalid("holding.evidence")
        if record.instrument_id is None and record.listing_id is not None:
            invalid("holding.listing")
    elif name == "XrayConstituentCandidate":
        _unique(tuple(item.id for item in record.holdings), "holdings")
        _unique(tuple(item.source_key for item in record.holdings), "holdings.source_key")
        _candidate_headers(record)
    elif name == "XrayFundEdge":
        if (record.origin == "holding") != (record.holding_id is not None):
            invalid("edge.origin")
    elif name == "XrayRelationshipVersion":
        _relationship_shape(record)
    elif name in ("XrayClassificationAssignment", "XrayClassificationSubject"):
        from trading212_domain.xray import XrayDimension, XraySubjectKind

        if record.dimension is XrayDimension.COMPANY or record.subject_kind not in (
            XraySubjectKind.ENTITY,
            XraySubjectKind.INSTRUMENT,
        ):
            invalid("classification.subject")
    elif name == "XrayPathClassification":
        if (record.bucket_key is None) != (record.reason is not None):
            invalid("classification.availability")
    elif name == "XrayClassificationDecision":
        for name in ("assignment_ids", "evidence_ids", "source_reference_ids"):
            bound(len(getattr(record, name)) <= 256, name)
        if (record.bucket_key is None) != (record.reason is not None):
            invalid("classification.availability")
    elif name == "XrayClassificationBatch":
        from trading212_domain.xray import XraySourceState

        _unique(record.requested_subjects, "classification.requested_subjects")
        if not record.assignments and not record.requested_subjects:
            invalid("classification.requested_subjects")
        if record.evidence.state is XraySourceState.GAP and record.assignments:
            invalid("classification.gap_assignments")
    elif name == "XrayTerminalPath":
        bound(len(record.fund_edges) <= 4, "fund_edges")
        bound(len(record.identity_decision_ids) <= 256, "identity_decision_ids")
        bound(len(record.source_reference_ids) <= 256, "source_reference_ids")
        _unique(record.identity_decision_ids, "identity_decision_ids")
        _unique(record.source_reference_ids, "source_reference_ids")
        if (
            sum(
                (
                    record.entity_id is not None,
                    record.explicit_cash,
                    record.unresolved_reason is not None,
                )
            )
            != 1
        ):
            invalid("path.partition")
    elif name == "CanonicalOverlapPair":
        bound(record.common_entity_count <= 10_000, "pair.common_entity_count")
    elif name == "CanonicalCommonEntities":
        if record.pair.common_entity_count != len(record.entities):
            invalid("pair.common_entity_count")
    elif name == "CanonicalFundPair":
        if str(record.first_fund_id) >= str(record.second_fund_id):
            invalid("pair.order")
    elif name == "XrayDisplayResidual":
        from trading212_domain.xray import XrayResidualKind

        is_weight = record.kind in (
            XrayResidualKind.WEIGHT_PARTITION,
            XrayResidualKind.UNIT_PARENT_CHILD,
        )
        if (record.currency is None) != is_weight:
            invalid("residual.currency")
        shape = record.coefficient.as_tuple()
        assert isinstance(shape.exponent, int)
        if record.value != Decimal((shape.sign, shape.digits, shape.exponent - 18)):
            invalid("residual.value")
    elif name == "XrayCommonEntitiesTop":
        bound(record.returned_count <= 50, "top.returned_count")
        if record.returned_count != len(record.items) or (
            record.returned_count + record.omitted_count != record.total_count
        ):
            invalid("top.counts")
    elif name == "XrayQualityCoverage":
        bound(record.root_count <= 10_000, "quality_coverage.root_count")
        bound(record.inferred_mapping_count <= 100_000, "quality_coverage.inferred_mapping_count")
        if record.valued_root_count > record.root_count:
            invalid("quality_coverage.valued_roots")
    elif name == "XrayThresholdConclusion":
        if record.metric not in ("top1", "top5", "hhi"):
            invalid("threshold.metric")
        if (record.breached is None) != (record.reason is not None):
            invalid("threshold.conclusion")
    elif name == "XrayTopConcentration":
        if record.count not in (1, 5, 10, 25, 50) or len(record.entity_ids) > record.count:
            invalid("top_concentration")
    elif name == "XrayExactState":
        bound(len(record.roots) <= 10_000 and record.visited_paths <= 10_000, "paths")
    elif name == "XrayInput":
        _input_bounds(record)
    elif name == "XrayCalculation":
        bound(len(record.terminal_paths) <= 10_000, "paths")
        bound(len(record.typed_source_uses) <= 100_000, "source_uses")
        if len(record.dimensions) != 6 or len(record.exact_state.dimensions) != 6:
            invalid("dimensions")


def _input_bounds(value: Any) -> None:
    bound(len(value.positions) <= 10_000, "positions")
    bound(len(value.positions) + len(value.cash) <= 10_000, "roots")
    currencies = {value.reporting_currency}
    currencies.update(item.root.original_currency for item in value.cash)
    currencies.update(
        item.original_value.value.currency
        for item in value.positions
        if item.original_value.value is not None
    )
    currencies.update(
        currency
        for conversion in value.licensed_fx
        for leg in conversion.legs
        for currency in (leg.base_currency, leg.quote_currency)
    )
    currencies.update(
        conversion.input_value.value.currency
        for conversion in value.licensed_fx
        if conversion.input_value.value is not None
    )
    bound(len(currencies) <= 32, "currencies")
    bound(len(value.constituent_candidates) <= 256, "constituent_candidates")
    bound(
        sum(len(item.holdings) for item in value.constituent_candidates) <= 100_000,
        "constituent_rows",
    )
    bound(
        len(value.entity_evidence)
        + len(value.relationship_versions)
        + sum(_classification_row_count(item) for item in value.classification_batches)
        <= 100_000,
        "identity_classification_rows",
    )
    roots = (*value.positions, *value.cash)
    _unique(tuple(item.root.key for item in roots), "root_keys")
    _unique(tuple(item.id for item in value.source_dependencies), "source_dependencies")
    for item in value.cash:
        if (
            item.original_value.value is not None
            and item.original_value.value.currency != item.root.original_currency
        ):
            invalid("cash.original_currency")
        if (
            item.reporting_value.value is not None
            and item.root.original_currency != value.reporting_currency
            and not item.fx_refs
        ):
            invalid("cash.fx_provenance")
    for item in roots:
        for metric in (item.original_value, item.reporting_value):
            if metric.value is not None and metric.value.amount < ZERO:
                invalid("root.amount")
        if item.reporting_value.value is not None and (
            item.reporting_value.value.currency != value.reporting_currency
        ):
            invalid("root.currency")
    for item in value.source_dependencies:
        if (item.owner_id, item.account_id, item.snapshot_id) != (
            value.owner_id,
            value.account_id,
            value.snapshot_id,
        ) or (
            item.provider_id is not None
            and item.provider_id not in value.policy.provider_selection_policy.provider_order
        ):
            invalid("dependency.binding")

    from trading212_domain.xray import (
        XrayBound,
        XrayDependencyKind,
        XrayReferenceKind,
        XraySubjectKind,
    )

    dependencies = {item.id: item for item in value.source_dependencies}
    for root in roots:
        for references in (
            root.valuation_refs,
            root.fx_refs,
            root.original_value.source_reference_ids,
            root.reporting_value.source_reference_ids,
        ):
            bound(len(references) <= 256, "root.source_references")
            _unique(references, "root.source_references")
        if (
            root.reporting_value.value is not None
            and root.reporting_value.bound is not XrayBound.EXACT
        ):
            invalid("root.inexact_basis")
    _licensed_fx_bindings(value, dependencies)
    _broker_fx_bindings(value, dependencies)
    for root in roots:
        subject = (
            root.root.position_id
            if hasattr(root.root, "position_id")
            else root.root.snapshot_cash_id
        )
        kind = (
            XrayReferenceKind.SNAPSHOT_POSITION
            if hasattr(root.root, "position_id")
            else XrayReferenceKind.SNAPSHOT_CASH
        )
        if root.reporting_value.value is not None and not any(
            reference in dependencies
            and dependencies[reference].kind is XrayDependencyKind.VALUATION
            and dependencies[reference].reference.kind is kind
            and dependencies[reference].reference.record_id == subject
            for reference in root.valuation_refs
        ):
            invalid("root.snapshot_anchor")
    bindings = (
        (
            value.fund_definitions,
            XrayDependencyKind.FUND_DEFINITION,
            XraySubjectKind.INSTRUMENT,
            "instrument_id",
        ),
        (
            value.fund_mappings,
            XrayDependencyKind.FUND_MAPPING,
            XraySubjectKind.INSTRUMENT,
            "fund_instrument_id",
        ),
        (
            value.constituent_candidates,
            XrayDependencyKind.CONSTITUENTS,
            XraySubjectKind.FUND_MAPPING,
            "fund_mapping_id",
        ),
        (
            value.entity_evidence,
            XrayDependencyKind.IDENTITY,
            XraySubjectKind.INSTRUMENT,
            "instrument_id",
        ),
    )
    for records, dependency_kind, subject_kind, subject_field in bindings:
        for record in records:
            dependency = dependencies.get(record.evidence.source_reference_id)
            if dependency is None or (
                dependency.kind,
                dependency.subject_kind,
                dependency.subject_id,
            ) != (dependency_kind, subject_kind, getattr(record, subject_field)):
                invalid("source.subject_binding")
    from trading212_domain.xray import XrayRelationshipKind

    for record in value.relationship_versions:
        dependency = dependencies.get(record.evidence.source_reference_id)
        subject_kind, subject = (
            (XraySubjectKind.LISTING, record.listing_id)
            if record.kind is XrayRelationshipKind.LISTING_OF
            else (XraySubjectKind.ENTITY, record.entity_id)
            if record.kind is XrayRelationshipKind.ISSUER_PARENT
            else (XraySubjectKind.INSTRUMENT, record.instrument_id)
        )
        if dependency is None or (
            dependency.kind,
            dependency.subject_kind,
            dependency.subject_id,
        ) != (XrayDependencyKind.RELATIONSHIP, subject_kind, subject):
            invalid("relationship.subject_binding")
    for batch in value.classification_batches:
        dependency = dependencies.get(batch.evidence.source_reference_id)
        if dependency is None or dependency.kind is not XrayDependencyKind.CLASSIFICATION:
            invalid("classification.source_binding")
        if dependency.subject_kind is XraySubjectKind.SOURCE_RECORD:
            if dependency.subject_id != batch.evidence.id:
                invalid("classification.record_binding")
        elif any(
            (row.subject_kind, row.subject_id) != (dependency.subject_kind, dependency.subject_id)
            for row in (*batch.assignments, *batch.requested_subjects)
        ):
            invalid("classification.subject_binding")


def _classification_row_count(batch: Any) -> int:
    # Membership metadata for an available row does not consume another candidate.
    assigned = {
        (row.subject_kind, row.subject_id, row.dimension, row.taxonomy_id, row.taxonomy_version)
        for row in batch.assignments
    }
    missing = sum(
        (row.subject_kind, row.subject_id, row.dimension, row.taxonomy_id, row.taxonomy_version)
        not in assigned
        for row in batch.requested_subjects
    )
    return len(batch.assignments) + missing


def exact_context() -> Context:
    """Shared fully specified context for the closed X-ray source/coefficient algebra."""
    return Context(
        prec=256,
        rounding=ROUND_HALF_EVEN,
        Emin=-999,
        Emax=999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[
            Inexact,
            Rounded,
            InvalidOperation,
            DivisionByZero,
            Overflow,
            Underflow,
            Subnormal,
            Clamped,
            FloatOperation,
        ],
    )


def _candidate_headers(record: Any) -> None:
    from trading212_domain.xray import XrayHoldingKind

    headers = (record.stated_coverage, record.unresolved_weight, record.cash_weight)
    if any(value is None for value in headers):
        from trading212_domain.xray import XraySourceState

        if (
            not all(value is None for value in headers)
            or record.holdings
            or record.evidence.state is not XraySourceState.GAP
        ):
            invalid("constituents.unavailable_headers")
        return
    context = exact_context()
    total = context.add(
        context.add(record.stated_coverage, record.unresolved_weight), record.cash_weight
    )
    if total > ONE:
        invalid("constituents.header_oversum")
    rows = {kind: ZERO for kind in XrayHoldingKind}
    for holding in record.holdings:
        rows[holding.kind] = context.add(rows[holding.kind], holding.weight)
    resolved = context.add(rows[XrayHoldingKind.INSTRUMENT], rows[XrayHoldingKind.ENTITY])
    if (
        resolved > record.stated_coverage
        or rows[XrayHoldingKind.CASH] > record.cash_weight
        or (rows[XrayHoldingKind.UNRESOLVED] > record.unresolved_weight)
    ):
        invalid("constituents.header_row_contradiction")
    if any(context.flags.values()):
        invalid("constituents.arithmetic")


def canonical_provider(value: str) -> None:
    try:
        if str(UUID(value)) == value:
            return
    except ValueError:
        pass
    invalid("provider_id")


def _dependency_shape(record: Any) -> None:
    from trading212_domain.xray import XrayDependencyKind as D
    from trading212_domain.xray import XrayReferenceKind as K

    allowed = {
        D.VALUATION: (
            K.SNAPSHOT_POSITION,
            K.SNAPSHOT_CASH,
            K.PORTFOLIO_SNAPSHOT,
            K.CALCULATION_RUN,
            K.BROKER_SOURCE_RECORD,
            K.PRICE_SNAPSHOT,
            K.PRICE_OBSERVATION,
        ),
        D.RECONCILIATION: (K.RECONCILIATION_RUN, K.RECONCILIATION_DISCREPANCY),
        D.THRESHOLD: (K.OWNER_POLICY,),
        D.FX: (K.FX_SNAPSHOT, K.FX_OBSERVATION, K.FX_COVERAGE_GAP),
        D.BROKER_FX: (K.BROKER_SOURCE_RECORD,),
        D.FUND_DEFINITION: (K.FUND_DEFINITION,),
        D.FUND_MAPPING: (K.FUND_MAPPING,),
        D.CONSTITUENTS: (K.CONSTITUENT_SNAPSHOT, K.CONSTITUENT_HOLDING),
        D.IDENTITY: (K.ENTITY_EVIDENCE_VERSION, K.ENTITY_EVIDENCE_REFERENCE),
        D.RELATIONSHIP: (K.RELATIONSHIP,),
        D.CLASSIFICATION: (K.CLASSIFICATION_SNAPSHOT, K.CLASSIFICATION_ASSIGNMENT),
    }
    if record.reference.kind not in allowed[record.kind]:
        invalid("dependency.reference_kind")
    internal = record.reference.kind in (
        K.SNAPSHOT_POSITION,
        K.SNAPSHOT_CASH,
        K.PORTFOLIO_SNAPSHOT,
        K.CALCULATION_RUN,
        K.RECONCILIATION_RUN,
        K.RECONCILIATION_DISCREPANCY,
        K.OWNER_POLICY,
        K.BROKER_SOURCE_RECORD,
    )
    if internal:
        if record.provider_id is not None or record.license_version_id is not None:
            invalid("dependency.internal_license")
    elif record.provider_id is None or record.license_version_id is None:
        invalid("dependency.licensed_source")
    else:
        canonical_provider(record.provider_id)
    if record.reference.kind in (K.SNAPSHOT_POSITION, K.SNAPSHOT_CASH) and (
        record.reference.parent_record_id != record.snapshot_id
        or record.reference.record_id != record.subject_id
    ):
        invalid("dependency.snapshot_membership")
    if record.reference.kind is K.BROKER_SOURCE_RECORD and (
        record.reference.parent_record_id != record.account_id
    ):
        invalid("dependency.broker_account")
    if (
        record.reference.kind is K.PORTFOLIO_SNAPSHOT
        and record.reference.record_id != record.snapshot_id
    ):
        invalid("dependency.portfolio_snapshot")


def _broker_fx_bindings(value: Any, dependencies: dict[UUID, Any]) -> None:
    from trading212_domain.xray import XrayDependencyKind as D
    from trading212_domain.xray import XrayReferenceKind as K
    from trading212_domain.xray import XraySubjectKind as S

    bound(len(value.broker_fx) <= 10_000, "broker_fx")
    _unique(tuple(item.root_key for item in value.broker_fx), "broker_fx.roots")
    positions = {item.root.key: item for item in value.positions}
    retained = {(item.root_key, item.source_reference_id) for item in value.broker_fx}
    conversions = {item.consumer_key: item for item in value.licensed_fx}
    for quote in value.broker_fx:
        root = positions.get(quote.root_key)
        dependency = dependencies.get(quote.source_reference_id)
        calculation = dependencies.get(quote.calculation_reference_id)
        if root is None or root.root.listing_id != quote.listing_id:
            invalid("broker_fx.listing")
        if dependency is None or (
            dependency.kind,
            dependency.subject_kind,
            dependency.subject_id,
            dependency.reference.kind,
            dependency.reference.record_id,
        ) != (
            D.BROKER_FX,
            S.SOURCE_RECORD,
            quote.source_record_id,
            K.BROKER_SOURCE_RECORD,
            quote.source_record_id,
        ):
            invalid("broker_fx.source_record")
        if (
            calculation is None
            or calculation.kind is not D.VALUATION
            or (calculation.reference.kind, calculation.reference.record_id)
            != (K.CALCULATION_RUN, quote.calculation_run_id)
        ):
            invalid("broker_fx.calculation")
        if (
            quote.source_reference_id not in root.fx_refs
            or quote.calculation_reference_id not in root.valuation_refs
        ):
            invalid("broker_fx.root_provenance")
        if (
            quote.observed_at > value.valuation_at
            or quote.source_observed_at > value.source_cutoff_at
        ):
            invalid("broker_fx.cutoff")
        conversion = conversions.get(quote.root_key)
        saved = root.reporting_value if conversion is None else conversion.input_value
        if (
            root.original_value.value is None
            or root.original_value.value.currency != quote.base_currency
            or (saved.value is not None and quote.quote_currency != saved.value.currency)
        ):
            invalid("broker_fx.currency")
    for root in (*value.positions, *value.cash):
        for reference in root.fx_refs:
            dependency = dependencies.get(reference)
            if dependency is None or dependency.kind not in (D.FX, D.BROKER_FX):
                invalid("root.fx_reference")
            if dependency.kind is D.BROKER_FX and (root.root.key, reference) not in retained:
                invalid("broker_fx.missing_quote")


def _licensed_fx_bindings(value: Any, dependencies: dict[UUID, Any]) -> None:
    from trading212_domain.xray import XrayDependencyKind as D
    from trading212_domain.xray import XrayReferenceKind as K
    from trading212_domain.xray import XraySubjectKind as S

    bound(len(value.licensed_fx) <= 10_001, "licensed_fx")
    _unique(tuple(item.consumer_key for item in value.licensed_fx), "licensed_fx.consumers")
    roots = {item.root.key: item for item in (*value.positions, *value.cash)}
    retained: set[tuple[str, UUID]] = set()
    currencies = {value.reporting_currency}
    for conversion in value.licensed_fx:
        root = roots.get(conversion.consumer_key)
        if conversion.consumer_key != "portfolio_total" and root is None:
            invalid("licensed_fx.consumer")
        if conversion.output_currency != value.reporting_currency:
            invalid("licensed_fx.currency")
        input_metric = conversion.input_value
        if root is None:
            output_metric = value.portfolio_total
            references = output_metric.source_reference_ids
            required_kind, required_id = K.PORTFOLIO_SNAPSHOT, value.snapshot_id
        else:
            output_metric = root.reporting_value
            references = root.fx_refs
            is_position = hasattr(root.root, "position_id")
            required_kind = K.SNAPSHOT_POSITION if is_position else K.SNAPSHOT_CASH
            required_id = root.root.position_id if is_position else root.root.snapshot_cash_id
            if not set(input_metric.source_reference_ids).issubset(
                set(root.valuation_refs + root.fx_refs)
            ):
                invalid("licensed_fx.input_provenance")
        if not any(
            reference in dependencies
            and dependencies[reference].kind is D.VALUATION
            and dependencies[reference].reference.kind is required_kind
            and dependencies[reference].reference.record_id == required_id
            for reference in input_metric.source_reference_ids
        ):
            invalid("licensed_fx.snapshot_anchor")
        unavailable = not conversion.legs or any(
            leg.rate is None or leg.quality.value == "failed" for leg in conversion.legs
        )
        if (output_metric.value is None) != unavailable:
            invalid("licensed_fx.output_value")
        providers: set[str] = set()
        for leg in conversion.legs:
            dependency = dependencies.get(leg.source_reference_id)
            reference_kind, record_id = (
                (K.FX_OBSERVATION, leg.observation_id)
                if leg.observation_id is not None
                else (K.FX_COVERAGE_GAP, leg.coverage_gap_id)
            )
            if (
                dependency is None
                or dependency.kind is not D.FX
                or (
                    dependency.reference.kind,
                    dependency.reference.record_id,
                    dependency.reference.parent_record_id,
                )
                != (reference_kind, record_id, leg.snapshot_id)
            ):
                invalid("licensed_fx.observation")
            if (dependency.subject_kind, dependency.subject_id) != (S.SOURCE_RECORD, record_id):
                invalid("licensed_fx.subject")
            providers.add(dependency.provider_id)
            if leg.source_reference_id not in references:
                invalid("licensed_fx.provenance")
            if leg.observed_at > value.valuation_at or leg.first_known_at > value.source_cutoff_at:
                invalid("licensed_fx.cutoff")
            currencies.update((leg.base_currency, leg.quote_currency))
            retained.add((conversion.consumer_key, leg.source_reference_id))
        if len(providers) > 1:
            invalid("licensed_fx.common_provider")
    bound(len(currencies) <= 32, "licensed_fx.currencies")
    consumers = [(root.root.key, root.fx_refs) for root in roots.values()]
    consumers.append(("portfolio_total", value.portfolio_total.source_reference_ids))
    for consumer, references in consumers:
        for reference in references:
            dependency = dependencies.get(reference)
            if (
                dependency is not None
                and dependency.kind is D.FX
                and (consumer, reference) not in retained
            ):
                invalid("licensed_fx.missing_quote")


def _relationship_shape(record: Any) -> None:
    from trading212_domain.xray import XrayRelationshipKind as K

    present = {
        name
        for name in (
            "instrument_id",
            "underlying_instrument_id",
            "entity_id",
            "listing_id",
            "share_class_id",
            "parent_entity_id",
        )
        if getattr(record, name) is not None
    }
    required = {
        K.LISTING_OF: {"listing_id", "instrument_id"},
        K.SHARE_CLASS: {"instrument_id", "share_class_id", "entity_id"},
        K.DEPOSITARY_RECEIPT: {"instrument_id", "underlying_instrument_id", "entity_id"},
        K.ISSUER_PARENT: {"entity_id", "parent_entity_id"},
    }[record.kind]
    if present != required:
        invalid("relationship.endpoints")
    if record.kind is K.DEPOSITARY_RECEIPT:
        if record.instrument_id == record.underlying_instrument_id or (
            record.units_per_receipt is not None and record.units_per_receipt <= ZERO
        ):
            invalid("relationship.receipt")
    elif record.units_per_receipt is not None:
        invalid("relationship.receipt")
    if record.kind is K.ISSUER_PARENT and record.entity_id == record.parent_entity_id:
        invalid("relationship.parent")
