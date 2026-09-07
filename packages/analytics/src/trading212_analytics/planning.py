"""Cutoff-pinned drift and planning over exact, transport-free domain values."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException, localcontext

from trading212_domain.currency_policy import monetary_quantum
from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError, fail_validation
from trading212_domain.planning import (
    DRIFT_METHOD,
    PLAN_METHOD,
    PLANNING_QUANTUM,
    ContributionPlanResult,
    ContributionPlanResultSummary,
    CoveragePolicy,
    DriftBasis,
    DriftCalculation,
    DriftRow,
    DriftTotals,
    PlanningAvailability,
    PlanningConstraint,
    PlanningContext,
    PlanningCoverage,
    PlanningExplanation,
    PlanningFxRate,
    PlanningInput,
    PlanningMode,
    PlanningSource,
    PlanOutcome,
)
from trading212_domain.planning_serialization import canonical_planning_input, planning_input_digest
from trading212_domain.targets import (
    FlattenedTargetNode,
    TargetConstraint,
    TargetMappingState,
    TargetNode,
    TargetNodeKind,
    flatten_target_content,
    target_content_digest,
    validate_target_content,
)
from trading212_domain.targets import (
    TargetConstraintKind as Kind,
)
from trading212_domain.values import Money, exact_decimal

ZERO = Decimal(0)
ONE = Decimal(1)


def _context() -> Context:
    return Context(prec=80, rounding=ROUND_HALF_EVEN)


def quantized(value: Decimal) -> Decimal:
    return exact_decimal(value.quantize(PLANNING_QUANTUM))


def _money(value: Decimal, input: PlanningInput) -> Money:
    return Money(quantized(value), input.valuation.reporting_currency)


def _multiple(value: Decimal, quantum: Decimal) -> bool:
    return value % quantum == 0


def effective_constraints(value: PlanningInput) -> tuple[TargetConstraint, ...]:
    with localcontext(_context()):
        return _effective_constraints(value)


def _effective_constraints(value: PlanningInput) -> tuple[TargetConstraint, ...]:
    """Resolve UUID overrides and reject shape errors or relaxation of frozen bounds."""
    node_keys = {x.id: x.key for x in value.node_identities}
    effective = {(x.node_key, x.kind): x for x in value.target_content.constraints}
    if len(effective) != len(value.target_content.constraints) or len(
        {x.key for x in value.target_content.constraints}
    ) != len(value.target_content.constraints):
        fail_validation("Published constraint scopes and keys must be unique.", field="constraints")
    seen: set[tuple[str | None, Kind]] = set()
    original_keys = {x.key: (x.node_key, x.kind) for x in value.target_content.constraints}
    holdings = {x.holding_id: x for x in value.node_identities if x.holding_id is not None}
    overrides = list(value.options.allocation_constraints)
    for composite in value.options.holding_constraints:
        identity = holdings.get(composite.holding_id)
        if identity is None:
            fail_validation(
                "Holding constraint does not belong to the pinned target.", field="holding_id"
            )
        for kind, amount in (
            (Kind.MINIMUM_FUNDED_AMOUNT, composite.minimum_amount),
            (Kind.AMOUNT_INCREMENT, composite.value_increment),
        ):
            overrides.append(
                PlanningConstraint(
                    "holding-" + composite.holding_id + "-" + kind.value,
                    kind,
                    identity.id,
                    amount=amount,
                    currency=value.valuation.reporting_currency,
                )
            )
        if composite.maximum_post_weight is not None:
            overrides.append(
                PlanningConstraint(
                    "holding-" + composite.holding_id + "-maximum_post_weight",
                    Kind.MAXIMUM_POST_WEIGHT,
                    identity.id,
                    weight=composite.maximum_post_weight,
                )
            )
    for override in overrides:
        key = node_keys.get(override.node_id) if override.node_id else None
        if override.node_id is not None and key is None:
            fail_validation(
                "Constraint node does not belong to the pinned target.", field="node_id"
            )
        item = TargetConstraint(
            override.key,
            override.kind,
            key,
            override.amount,
            override.currency,
            override.weight,
            override.enabled,
            override.count,
            override.coefficient,
        )
        scope = (key, item.kind)
        if scope in seen or (item.key in original_keys and original_keys[item.key] != scope):
            fail_validation(
                "Constraint overrides must have unique scope and keys.",
                field="allocation_constraints",
            )
        seen.add(scope)
        old = effective.get(scope)
        if old is not None:
            low = {Kind.MINIMUM_FUNDED_AMOUNT, Kind.MINIMUM_POST_WEIGHT, Kind.MINIMUM_GROUP_FUNDING}
            high = {Kind.MAXIMUM_POST_WEIGHT, Kind.MAXIMUM_GROUP_FUNDING, Kind.MAXIMUM_FUNDED_LINES}
            if item.kind in low | high:
                field = (
                    "weight"
                    if item.kind in {Kind.MINIMUM_POST_WEIGHT, Kind.MAXIMUM_POST_WEIGHT}
                    else "count"
                    if item.kind is Kind.MAXIMUM_FUNDED_LINES
                    else "amount"
                )
                new_value, old_value = getattr(item, field), getattr(old, field)
                if (
                    new_value is None
                    or old_value is None
                    or (new_value < old_value if item.kind in low else new_value > old_value)
                ):
                    fail_validation(
                        "An override cannot relax a published hard constraint.",
                        field="allocation_constraints",
                    )
            elif item.kind is Kind.AMOUNT_INCREMENT:
                if (
                    item.amount is None
                    or old.amount is None
                    or item.amount <= 0
                    or item.amount % old.amount
                ):
                    fail_validation(
                        "An override increment must preserve the published grid.",
                        field="allocation_constraints",
                    )
            elif item.kind is Kind.ELIGIBLE and old.enabled is False and item.enabled is not False:
                fail_validation(
                    "An override cannot enable an excluded holding.", field="allocation_constraints"
                )
            elif item.kind is Kind.CASH_RESERVE:
                if any(
                    getattr(old, field) is not None
                    and (getattr(item, field) is None or getattr(item, field) < getattr(old, field))
                    for field in ("amount", "weight")
                ):
                    fail_validation(
                        "An override cannot reduce the published reserve.",
                        field="allocation_constraints",
                    )
        effective[scope] = item
    constraints = tuple(sorted(effective.values(), key=lambda x: x.key))
    if len(constraints) > 1280 or len({x.key for x in constraints}) != len(constraints):
        fail_validation(
            "Effective constraints exceed the bounded unique schema.",
            field="allocation_constraints",
        )
    # The published schema remains bounded at 256; derived overrides are checked in
    # bounded batches after global uniqueness checks, without loosening that schema.
    for start in range(0, len(constraints), 256):
        checked = validate_target_content(
            replace(value.target_content, constraints=constraints[start : start + 256]),
            reporting_currency=value.valuation.reporting_currency,
            effective_at=value.target_effective_at,
            catalog=value.catalog,
        )
        if any(
            x.code
            in {
                "constraint_scope_invalid",
                "constraint_fields_invalid",
                "duplicate_constraint_key",
                "duplicate_constraint_kind",
            }
            for x in checked.issues
        ):
            fail_validation(
                "Constraint fields or scope are invalid.", field="allocation_constraints"
            )
    return constraints


def validate_planning_input(value: PlanningInput) -> PlanningInput:
    """Validate bounded command semantics; analytical infeasibility remains a result."""
    if not isinstance(value, PlanningInput):
        fail_validation("A typed planning input is required.")
    with localcontext(_context()):
        value = canonical_planning_input(value)
        if value.options.contribution.currency != value.valuation.reporting_currency:
            fail_validation(
                "Contribution and reporting currencies must match.", field="contribution"
            )
        quantum = monetary_quantum(
            value.valuation.reporting_currency, value.options.monetary_quantum
        )
        value = replace(value, options=replace(value.options, monetary_quantum=quantum))
        nodes = {x.key: x for x in value.target_content.nodes}
        kinds = {
            (x.holding_id if nodes[x.key].kind is TargetNodeKind.HOLDING else x.id): nodes[
                x.key
            ].kind
            for x in value.node_identities
        }
        for collection, required in (
            (value.options.eligible_holding_ids or (), TargetNodeKind.HOLDING),
            (value.options.excluded_holding_ids, TargetNodeKind.HOLDING),
            (value.options.restricted_group_ids, TargetNodeKind.GROUP),
        ):
            if any(kinds.get(x) is not required for x in collection):
                fail_validation(
                    "Selected nodes do not belong to the required pinned scope.", field="node_ids"
                )
        listing_map = {str(x.listing_id): x for x in value.catalog.listings}
        identities = {
            x.holding_id: nodes[x.key] for x in value.node_identities if x.holding_id is not None
        }
        for preference in value.options.listing_preferences:
            node = identities.get(preference.holding_id)
            listing = listing_map.get(preference.listing_id)
            if (
                node is None
                or node.kind is not TargetNodeKind.HOLDING
                or node.holding is None
                or listing is None
                or listing.instrument_id != node.holding.instrument_id
                or (
                    node.holding.listing_id is not None
                    and str(node.holding.listing_id) != preference.listing_id
                )
            ):
                fail_validation(
                    "Funding preference does not match the pinned holding.",
                    field="listing_preferences",
                )
        constraints = effective_constraints(value)
        amounts = [
            value.options.contribution.amount,
            *(
                x.amount
                for x in constraints + value.target_content.constraints
                if x.amount is not None
            ),
        ]
        if value.options.cash_reserve is not None:
            amounts.append(value.options.cash_reserve)
        if quantum is not None and any(not _multiple(x, quantum) for x in amounts):
            fail_validation(
                "Planning amounts must be exact monetary-quantum multiples.",
                field="monetary_quantum",
            )
        # The persisted money contract bounds aggregates as well as individual
        # scalars. Reject unsupported magnitude before a durable request exists.
        converted_positions = [_convert(x.value, x.fx, value)[0] for x in value.valuation.positions]
        converted_cash = [
            _convert(x.value, x.fx, value)[0] for x in value.valuation.cash_components
        ]
        quantized(sum((x for x in (*converted_positions, *converted_cash) if x is not None), ZERO))
        if value.valuation.portfolio_total is not None:
            quantized(value.valuation.portfolio_total.amount + value.options.contribution.amount)
        return value


@dataclass(frozen=True, slots=True)
class _Component:
    key: str
    node: TargetNode | None
    depth: int
    target: Decimal
    value: Decimal | None
    quality: QualityState
    listing_id: str | None = None
    instrument_id: str | None = None


@dataclass(frozen=True, slots=True)
class _Problem:
    input: PlanningInput
    flattened: tuple[FlattenedTargetNode, ...]
    components: tuple[_Component, ...]
    holdings: tuple[_Component, ...]
    constraints: tuple[TargetConstraint, ...]
    cash_key: str
    current_cash: Decimal | None
    total: Decimal | None
    known_total: Decimal
    unclassified: Decimal
    matched: Decimal
    unresolved_weight: Decimal
    residual: Decimal | None
    unavailable: tuple[str, ...]
    warnings: tuple[PlanningExplanation, ...]
    quality: QualityState
    enabled: tuple[bool, ...]
    funding_listings: tuple[str | None, ...]
    unresolved: tuple[str, ...]


_QUALITY_ORDER = {
    value: index
    for index, value in enumerate(
        (
            QualityState.FRESH,
            QualityState.ESTIMATED,
            QualityState.STALE,
            QualityState.PARTIAL,
            QualityState.UNRECONCILED,
            QualityState.FAILED,
        )
    )
}


def _convert(
    value: Money | None, fx: PlanningFxRate | None, input: PlanningInput
) -> tuple[Decimal | None, str | None]:
    if value is None:
        return None, "missing_valuation"
    if value.amount < 0:
        return value.amount, "unsupported_negative_invest_valuation"
    if value.currency == input.valuation.reporting_currency:
        return value.amount, None
    if fx is None or fx.base != value.currency or fx.quote != input.valuation.reporting_currency:
        return None, "missing_fx"
    if (
        fx.source.effective_at > input.valuation.valuation_at
        or fx.source.first_observed_at > input.valuation.source_cutoff_at
    ):
        return None, "source_after_cutoff"
    return quantized(value.amount * fx.rate), None


def _prepare(value: PlanningInput, *, funding: bool = True) -> _Problem:
    flattened: tuple[FlattenedTargetNode, ...]
    residual: Decimal | None
    shape = flatten_target_content(value.target_content)
    unavailable: set[str] = set()
    warnings: list[PlanningExplanation] = []
    if (
        shape is None
        or target_content_digest(
            value.target_content,
            reporting_currency=value.valuation.reporting_currency,
            effective_at=value.target_effective_at,
        )
        != value.target_content_digest
    ):
        unavailable.add("invalid_target_configuration")
        flattened, residual = (), None
    else:
        flattened, residual = shape
    targets: dict[str, Decimal] = {}
    with localcontext(Context(prec=160, rounding=ROUND_HALF_EVEN)):
        for item in flattened:
            product = ONE
            for factor in item.path_factors:
                product *= factor
            targets[item.node.key] = product
    leaf_nodes = [x.node for x in flattened if x.node.kind is TargetNodeKind.HOLDING]
    values: dict[str, Decimal | None] = {x.key: ZERO for x in leaf_nodes}
    qualities: list[QualityState] = [value.valuation.quality]
    components: list[_Component] = []
    known_total, unclassified, matched = ZERO, ZERO, ZERO
    for position in value.valuation.positions:
        converted, reason = _convert(position.value, position.fx, value)
        qualities.append(position.quality)
        if reason:
            unavailable.add(reason)
        if converted is not None:
            known_total += converted
        selected = [
            node
            for node in leaf_nodes
            if node.holding is not None
            and node.holding.instrument_id is not None
            and str(node.holding.instrument_id) == position.instrument_id
            and (
                node.holding.listing_id is None
                or str(node.holding.listing_id) == position.listing_id
            )
        ]
        if len(selected) > 1:
            unavailable.add("overlapping_holding_selectors")
            selected = []
        if selected:
            key = selected[0].key
            previous = values[key]
            values[key] = None if previous is None or converted is None else previous + converted
            if converted is not None:
                matched += converted
        else:
            components.append(
                _Component(
                    "unclassified/" + position.listing_id,
                    None,
                    1,
                    ZERO,
                    converted,
                    position.quality,
                    position.listing_id,
                    position.instrument_id,
                )
            )
            if converted is not None:
                unclassified += converted
    cash_values = [_convert(x.value, x.fx, value) for x in value.valuation.cash_components]
    if not cash_values:
        unavailable.add("missing_cash_valuation")
    for _, reason in cash_values:
        if reason:
            unavailable.add(reason)
    qualities.extend(x.quality for x in value.valuation.cash_components)
    known_total += sum((x for x, _ in cash_values if x is not None), ZERO)
    cash = (
        None
        if not cash_values or any(x is None for x, _ in cash_values)
        else sum((x for x, _ in cash_values if x is not None), ZERO)
    )
    cash_node = next((x.node for x in flattened if x.node.kind is TargetNodeKind.CASH), None)
    cash_key = (
        "target/" + cash_node.key
        if cash_node
        else "cash/" + value.valuation.reporting_currency.value
    )
    for item in reversed(flattened):
        node = item.node
        if node.kind is TargetNodeKind.CASH:
            values[node.key] = cash
        elif node.kind is TargetNodeKind.GROUP:
            children = [values[x.node.key] for x in flattened if x.node.parent_key == node.key]
            values[node.key] = (
                None
                if any(x is None for x in children)
                else sum((x for x in children if x is not None), ZERO)
            )
    quality = max(qualities, key=_QUALITY_ORDER.__getitem__)
    components.extend(
        _Component(
            "target/" + x.node.key,
            x.node,
            x.depth,
            targets[x.node.key],
            values.get(x.node.key),
            quality,
            str(x.node.holding.listing_id)
            if x.node.holding and x.node.holding.listing_id
            else None,
            str(x.node.holding.instrument_id)
            if x.node.holding and x.node.holding.instrument_id
            else None,
        )
        for x in flattened
    )
    if cash_node is None:
        components.append(_Component(cash_key, None, 1, ZERO, cash, quality))
    total = value.valuation.portfolio_total.amount if value.valuation.portfolio_total else None
    if total is None:
        unavailable.add("missing_snapshot_total")
    elif total < 0:
        unavailable.add("unsupported_negative_invest_valuation")
    elif total != known_total:
        unavailable.add("valuation_total_mismatch")
    for source in value.valuation.sources:
        if source.kind in {"provider_observation", "provider_fx_observation", "fx_snapshot"} and (
            source.first_observed_at > value.valuation.source_cutoff_at
            or source.effective_at > value.valuation.valuation_at
        ):
            unavailable.add("source_after_cutoff")
    if (
        value.target_published_at > value.valuation.source_cutoff_at
        or value.target_effective_at > value.valuation.valuation_at
    ):
        warnings.append(
            PlanningExplanation(
                "explicit_later_target",
                (
                    "The explicitly selected target postdates this financial snapshot; "
                    "historical target knowledge or activation is not asserted."
                ),
                "info",
            )
        )
    degraded = (
        quality is not QualityState.FRESH
        or not value.valuation.coverage_complete
        or not value.valuation.reconciled
        or bool(value.valuation.missing_inputs)
    )
    if degraded:
        warnings.append(
            PlanningExplanation(
                "degraded_valuation_inputs",
                (
                    "Valuation quality, coverage, or reconciliation is degraded "
                    "under the recorded policy."
                ),
            )
        )
        if (
            value.options.coverage_policy is CoveragePolicy.REQUIRE_COMPLETE
            or quality is QualityState.FAILED
        ):
            unavailable.add("material_quality_gate")
        quality = max(
            (
                quality,
                QualityState.UNRECONCILED
                if not value.valuation.reconciled
                else QualityState.PARTIAL,
            ),
            key=_QUALITY_ORDER.__getitem__,
        )
    validation = validate_target_content(
        value.target_content,
        reporting_currency=value.valuation.reporting_currency,
        effective_at=value.target_effective_at,
        catalog=value.catalog,
    )
    for issue in validation.issues:
        if issue.code == "duplicate_economic_exposure":
            warnings.append(
                PlanningExplanation(issue.code, issue.message, node_keys=issue.node_keys)
            )
        elif issue.code in {
            "unknown_instrument",
            "unknown_listing",
            "listing_instrument_mismatch",
            "preferred_listing_mismatch",
            "overlapping_holding_selectors",
            "holding_mapping_required",
            "holding_mapping_not_allowed",
            "exclusion_scope_invalid",
            "exclusion_mapping_unknown",
            "duplicate_exclusion_key",
            "duplicate_exclusion_selector",
        }:
            unavailable.add("invalid_target_mapping")
    constraints = effective_constraints(value)
    holdings = tuple(
        sorted(
            (x for x in components if x.node and x.node.kind is TargetNodeKind.HOLDING),
            key=lambda x: x.node.key if x.node else "",
        )
    )
    identities = {x.key: x.holding_id for x in value.node_identities}
    paths = {x.node.key: x.path_keys for x in flattened}
    chosen_groups = {
        x.key for x in value.node_identities if x.id in value.options.restricted_group_ids
    }
    preferences = {x.holding_id: x.listing_id for x in value.options.listing_preferences}
    excluded_listings = {
        str(x.listing_id) for x in value.target_content.exclusions if x.listing_id is not None
    }
    can_fund = value.options.contribution.amount > 0 and not any(
        x.kind is Kind.MAXIMUM_FUNDED_LINES and x.count == 0 for x in constraints
    )
    enabled, listings, unresolved = [], [], []
    unresolved_weight = ZERO
    for holding_component in holdings:
        assert holding_component.node is not None
        node = holding_component.node
        mapping = node.holding
        node_id = identities[node.key]
        assert node_id is not None
        allowed = (
            funding
            and value.options.mode is not PlanningMode.CASH_ONLY
            and (
                value.options.eligible_holding_ids is None
                or node_id in value.options.eligible_holding_ids
            )
            and node_id not in value.options.excluded_holding_ids
        )
        if value.options.mode is PlanningMode.RESTRICTED and not chosen_groups.intersection(
            paths[node.key]
        ):
            allowed = False
        if any(
            x.kind is Kind.ELIGIBLE and x.node_key == node.key and x.enabled is False
            for x in constraints
        ):
            allowed = False
        for exclusion in value.target_content.exclusions:
            if exclusion.node_key == node.key or (
                mapping is not None
                and (
                    (
                        exclusion.instrument_id is not None
                        and exclusion.instrument_id == mapping.instrument_id
                    )
                    or (
                        exclusion.listing_id is not None
                        and exclusion.listing_id
                        in (mapping.listing_id, mapping.preferred_listing_id)
                    )
                )
            ):
                allowed = False
        if (
            mapping is None
            or mapping.state is not TargetMappingState.RESOLVED
            or mapping.instrument_id is None
        ):
            unresolved.append(node.key)
            unresolved_weight += holding_component.target
            warnings.append(
                PlanningExplanation(
                    "unresolved_target_mapping",
                    "The target mapping remains explicit and unresolved.",
                    node_keys=(node.key,),
                )
            )
            if allowed:
                unavailable.add("unresolved_material_mapping")
        needs_listing = allowed and can_fund
        selected_listing = None
        if mapping is not None:
            selected_listing = preferences.get(node_id) or (
                str(mapping.preferred_listing_id)
                if mapping.preferred_listing_id
                else str(mapping.listing_id)
                if mapping.listing_id
                else None
            )
            eligible = sorted(
                str(x.listing_id)
                for x in value.catalog.listings
                if x.instrument_id == mapping.instrument_id
                and x.eligible
                and str(x.listing_id) not in excluded_listings
            )
            if selected_listing in excluded_listings:
                allowed = False
                needs_listing = False
            if selected_listing is not None and selected_listing not in eligible:
                if needs_listing:
                    unavailable.add("funding_listing_unavailable")
            elif selected_listing is None and len(eligible) == 1:
                selected_listing = eligible[0]
            elif selected_listing is None and needs_listing:
                unavailable.add(
                    "listing_choice_required"
                    if len(eligible) > 1
                    else "funding_listing_unavailable"
                )
        enabled.append(allowed)
        listings.append(selected_listing)
    if unresolved:
        quality = max((quality, QualityState.PARTIAL), key=_QUALITY_ORDER.__getitem__)
    return _Problem(
        value,
        flattened,
        tuple(sorted(components, key=lambda x: x.key)),
        holdings,
        constraints,
        cash_key,
        cash,
        total
        if total == known_total and all(x.value is not None and x.value >= 0 for x in components)
        else None,
        known_total,
        unclassified,
        matched,
        unresolved_weight,
        residual,
        tuple(sorted(unavailable)),
        tuple(warnings),
        quality,
        tuple(enabled),
        tuple(listings),
        tuple(unresolved),
    )


def _result_context(
    problem: _Problem, method: str, *, reason: str | None = None, failed: bool = False
) -> PlanningContext:
    value = problem.input
    total = problem.total
    availability = (
        PlanningAvailability.FAILED
        if failed
        else PlanningAvailability.UNAVAILABLE
        if reason or problem.unavailable
        else PlanningAvailability.PARTIAL
        if problem.quality is not QualityState.FRESH
        else PlanningAvailability.AVAILABLE
    )
    sources = list(value.valuation.sources)
    sources.extend(x.fx.source for x in value.valuation.positions if x.fx is not None)
    sources.extend(x.fx.source for x in value.valuation.cash_components if x.fx is not None)
    sources.append(
        PlanningSource(
            "target_version",
            value.target_version_id,
            value.target_content_digest,
            value.method_version,
            value.target_effective_at,
            value.target_published_at,
        )
    )
    coverage = PlanningCoverage(
        not problem.unavailable and value.valuation.coverage_complete,
        _money(total, value) if total is not None else None,
        _money(problem.known_total, value),
        _money(problem.matched, value),
        _money(problem.unclassified, value),
        quantized(problem.matched / total) if total else None,
        quantized(problem.unclassified / total) if total else None,
        quantized(problem.unresolved_weight),
    )
    return PlanningContext(
        value.valuation.account_id,
        value.virtual_portfolio_id,
        value.target_version_id,
        value.valuation.snapshot_id,
        value.valuation.reporting_currency.value,
        value.valuation.valuation_at,
        value.valuation.source_cutoff_at,
        method,
        value.method_version,
        value.schema_version,
        planning_input_digest(value),
        tuple(sorted(set(sources), key=lambda x: (x.kind, x.id, x.content_digest))),
        availability,
        reason or (problem.unavailable[0] if problem.unavailable else None),
        problem.quality,
        value.valuation.valuation_at,
        value.valuation.valuation_at,
        tuple(
            sorted(
                set(problem.unavailable)
                | ({"degraded_source_coverage"} if value.valuation.missing_inputs else set())
            )
        ),
        value.valuation.reconciled,
        coverage,
        problem.warnings,
        (
            PlanningExplanation(
                "explicit_pinned_target",
                "The requested published target is a pinned comparison configuration.",
                "info",
            ),
            PlanningExplanation(
                "no_existing_cash_spending",
                "New contribution only; existing cash remains in the portfolio.",
                "info",
            ),
        ),
    )


def _priority(problem: _Problem, component: _Component) -> Decimal:
    return next(
        (
            x.coefficient
            for x in problem.constraints
            if x.kind is Kind.PRIORITY
            and component.node is not None
            and x.node_key == component.node.key
            and x.coefficient is not None
        ),
        ONE,
    )


def _drift(
    problem: _Problem,
    *,
    amounts: tuple[Decimal, ...] | None = None,
    residual_cash: Decimal = ZERO,
    basis: DriftBasis = DriftBasis.DIRECT,
    method: str = DRIFT_METHOD,
) -> DriftCalculation:
    value = problem.input
    current = {x.key: x.value for x in problem.components}
    total = problem.total
    if amounts is not None and total is not None:
        total += value.options.contribution.amount
        for component, amount in zip(problem.holdings, amounts, strict=True):
            if current[component.key] is not None:
                current[component.key] += amount  # type: ignore[operator]
        if current.get(problem.cash_key) is not None:
            current[problem.cash_key] += residual_cash  # type: ignore[operator]
        for item in reversed(problem.flattened):
            if item.node.kind is TargetNodeKind.GROUP:
                children = [
                    current["target/" + x.node.key]
                    for x in problem.flattened
                    if x.node.parent_key == item.node.key
                ]
                current["target/" + item.node.key] = (
                    None
                    if any(x is None for x in children)
                    else sum((x for x in children if x is not None), ZERO)
                )
    reason = (
        "effective_exposure_target_unavailable"
        if basis is DriftBasis.EFFECTIVE
        else "zero_valuation_denominator"
        if total == 0
        else problem.unavailable[0]
        if problem.unavailable
        else None
    )
    context = _result_context(problem, method, reason=reason)
    identities = {x.key: x for x in value.node_identities}
    rows = []
    leaf_scores, absolute = [], []
    frontier = []
    for component in problem.components:
        actual = current[component.key]
        weight = actual / total if actual is not None and total and not reason else None
        signed = weight - component.target if weight is not None else None
        node = component.node
        kind = (
            node.kind.value
            if node
            else "cash"
            if component.key == problem.cash_key
            else "unclassified"
        )
        if kind != "group":
            frontier.append(component.key)
            if signed is not None:
                absolute.append(abs(signed))
                leaf_scores.append(_priority(problem, component) * signed * signed)
        relative = None
        relative_reason = (
            "zero_target_weight"
            if component.target == 0
            else reason or ("valuation_unavailable" if signed is None else None)
        )
        if signed is not None and component.target > 0:
            try:
                relative = quantized(signed / component.target)
            except DomainError:
                relative_reason = "numeric_range_exceeded"
        rows.append(
            DriftRow(
                component.key,
                identities[node.key].id if node else None,
                identities[node.key].holding_id if node else None,
                kind,
                "target/" + node.parent_key if node and node.parent_key is not None else None,
                node.name if node else "Cash" if kind == "cash" else "Unclassified holding",
                component.depth,
                component.listing_id,
                component.instrument_id,
                quantized(component.target),
                _money(actual, value) if actual is not None else None,
                quantized(weight) if weight is not None else None,
                None,
                "effective_exposure_target_unavailable",
                quantized(signed) if signed is not None else None,
                quantized(abs(signed)) if signed is not None else None,
                relative,
                relative_reason,
                ("overweight" if signed > 0 else "underweight" if signed < 0 else "on_target")
                if signed is not None
                else None,
                _money(component.target * total - actual, value)
                if actual is not None and total is not None and not reason
                else None,
                problem.quality,
            )
        )
    usable = not reason and total is not None and total > 0 and len(leaf_scores) == len(frontier)
    cash_value = current.get(problem.cash_key)
    totals = DriftTotals(
        _money(total, value) if total is not None else None,
        _money(cash_value, value) if cash_value is not None else None,
        _money(problem.unclassified, value),
        quantized(sum(absolute, ZERO) / 2) if usable else None,
        quantized(sum(leaf_scores, ZERO)) if usable else None,
        problem.residual,
        tuple(frontier),
        sum(x.kind == "group" for x in rows),
        len(problem.holdings),
        sum(x.kind == "unclassified" for x in rows),
    )
    return DriftCalculation(context, totals, tuple(rows))


def calculate_drift(
    value: PlanningInput, *, basis: DriftBasis = DriftBasis.DIRECT
) -> DriftCalculation:
    if not isinstance(basis, DriftBasis):
        fail_validation("Unsupported drift basis.", field="basis")
    with localcontext(_context()):
        value = validate_planning_input(value)
        # Funding feasibility does not alter the identity of a drift observation.
        problem = _prepare(value, funding=False)
        return _drift(problem, basis=basis)


def _empty_result(
    problem: _Problem,
    outcome: PlanOutcome,
    reason: str,
    explanations: tuple[PlanningExplanation, ...] = (),
    *,
    attempted: int = 0,
    examined: int = 0,
    exhaustive: bool = False,
) -> ContributionPlanResult:
    value = problem.input
    before = _drift(problem)
    return ContributionPlanResult(
        ContributionPlanResultSummary(
            _result_context(
                problem, PLAN_METHOD, reason=reason, failed=outcome is PlanOutcome.FAILED
            ),
            outcome,
            value.options.mode,
            value.options.contribution,
            value.options.monetary_quantum,
            value.currency_policy_version,
            None,
            _money(problem.current_cash, value) if problem.current_cash is not None else None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            examined,
            attempted,
            exhaustive,
            problem.constraints,
            explanations
            or (
                PlanningExplanation(
                    reason,
                    (
                        "Exhaustive finite-domain search found no feasible allocation; "
                        "an individual conflicting constraint set was not isolated."
                    )
                    if reason == "finite_domain_exhausted"
                    else (
                        "The requested plan has no recommendations "
                        "under its recorded inputs or constraints."
                    ),
                ),
            ),
            tuple(
                x.node.key
                for x, allowed in zip(problem.holdings, problem.enabled, strict=True)
                if not allowed and x.node
            ),
            problem.unresolved,
            before.totals,
            None,
        ),
        (),
    )


def calculate_contribution_plan(value: PlanningInput) -> ContributionPlanResult:
    from ._contribution_solver import solve

    with localcontext(_context()):
        value = validate_planning_input(value)
        problem = _prepare(value)
        if value.options.monetary_quantum is None:
            return _empty_result(
                problem, PlanOutcome.UNAVAILABLE, "currency_minor_unit_unavailable"
            )
        if problem.unavailable:
            return _empty_result(problem, PlanOutcome.UNAVAILABLE, problem.unavailable[0])
        if problem.total is None or problem.total + value.options.contribution.amount == 0:
            return _empty_result(problem, PlanOutcome.UNAVAILABLE, "zero_valuation_denominator")
        try:
            result = solve(problem)
            verify_contribution_plan_result(value, result)
            return result
        except (DecimalException, DomainError, ArithmeticError, ValueError):
            pass
        return _empty_result(problem, PlanOutcome.FAILED, "internal_calculation_failure")


def verify_contribution_plan_result(value: PlanningInput, result: ContributionPlanResult) -> None:
    """Recheck immutable identity, conservation, hard constraints and every derived field.

    This is independent of guide/domain pruning and does not repeat the bounded
    search. Optimality labels remain backed by the persisted exhaustive-search
    evidence; this verifier never upgrades a bounded incumbent to optimal.
    """
    from ._contribution_solver import (
        MAX_ASSIGNMENTS,
        MAX_MOVES,
        _model,
        _result,
        contradiction_explanation,
        objective,
        valid_allocation,
    )

    valid = False
    with localcontext(_context()):
        value = validate_planning_input(value)
        if not isinstance(result, ContributionPlanResult):
            fail_validation("A typed contribution result is required.", field="result")
        problem = _prepare(value)
        summary = result.summary
        counts_valid = (
            type(summary.examined_moves) is int
            and 0 <= summary.examined_moves <= MAX_MOVES
            and type(summary.attempted_assignments) is int
            and 0 <= summary.attempted_assignments <= MAX_ASSIGNMENTS
            and type(summary.exhaustive) is bool
            and summary.execution_allowed is False
        )
        if counts_valid and summary.outcome in {
            PlanOutcome.OPTIMAL,
            PlanOutcome.FEASIBLE_NONOPTIMAL,
        }:
            if (
                not problem.unavailable
                and value.options.monetary_quantum is not None
                and problem.total is not None
                and problem.total + value.options.contribution.amount > 0
                and summary.residual_cash is not None
            ):
                amounts = tuple(x.recommended_amount.amount for x in result.lines)
                residual = summary.residual_cash.amount
                if valid_allocation(problem, amounts, residual):
                    model = _model(problem)
                    candidate = (objective(model, amounts, residual), residual, amounts)
                    expected = _result(
                        model,
                        candidate,
                        examined=summary.examined_moves,
                        attempted=summary.attempted_assignments,
                        exhaustive=summary.exhaustive,
                    )
                    valid = result == expected and (
                        (summary.outcome is PlanOutcome.OPTIMAL and summary.exhaustive)
                        or (
                            summary.outcome is PlanOutcome.FEASIBLE_NONOPTIMAL
                            and not summary.exhaustive
                            and summary.attempted_assignments == MAX_ASSIGNMENTS
                        )
                    )
        elif counts_valid:
            reason = summary.context.reason_code
            allowed_reason = False
            explanations: tuple[PlanningExplanation, ...] = ()
            if summary.outcome is PlanOutcome.FAILED:
                allowed_reason = reason == "internal_calculation_failure" and not summary.exhaustive
            elif summary.outcome is PlanOutcome.UNAVAILABLE:
                expected_reason = (
                    "currency_minor_unit_unavailable"
                    if value.options.monetary_quantum is None
                    else problem.unavailable[0]
                    if problem.unavailable
                    else "zero_valuation_denominator"
                    if problem.total is None
                    or problem.total + value.options.contribution.amount == 0
                    else None
                )
                allowed_reason = (reason == expected_reason and expected_reason is not None) or (
                    reason == "search_budget_exhausted"
                    and summary.attempted_assignments == MAX_ASSIGNMENTS
                )
                allowed_reason = allowed_reason and not summary.exhaustive
            elif (
                summary.outcome is PlanOutcome.INFEASIBLE
                and not problem.unavailable
                and value.options.monetary_quantum is not None
                and problem.total is not None
            ):
                proof = contradiction_explanation(_model(problem))
                if reason == "proved_constraint_contradiction" and proof is not None:
                    explanations = (proof,)
                allowed_reason = summary.exhaustive and (
                    reason == "finite_domain_exhausted"
                    or (reason == "proved_constraint_contradiction" and proof is not None)
                )
            if allowed_reason and reason is not None:
                valid = result == _empty_result(
                    problem,
                    summary.outcome,
                    reason,
                    explanations,
                    attempted=summary.attempted_assignments,
                    examined=summary.examined_moves,
                    exhaustive=summary.exhaustive,
                )
    if not valid:
        fail_validation("Contribution result failed independent verification.", field="result")
