"""Frozen single-entity research copier from 8fa5db7 for independent batch parity.

Only function names are adapted. This reference retains the old full per-item
pin/digest validation and all financial/quality/warning construction.
"""

from uuid import UUID

from trading212_domain.enums import QualityState, ValueOrigin
from trading212_domain.errors import fail_validation
from trading212_domain.research import ResearchExposureReason
from trading212_domain.research_facts import (
    ResearchPortfolioFacts,
    ResearchPortfolioWarning,
    ResearchXrayPin,
)
from trading212_domain.xray import XrayAvailability, XrayBound, XrayDimension, XrayReason
from trading212_domain.xray_result import XrayCalculation


def legacy_unvalued_entity_ids(value: XrayCalculation) -> frozenset[UUID]:
    """Identify held entities with no known money contribution in linear time."""
    if type(value) is not XrayCalculation:
        fail_validation("Canonical research exposure input is required.", field="portfolio_facts")
    unvalued: set[UUID] = set()
    known: set[UUID] = set()
    for path in value.terminal_paths:
        if path.entity_id is not None:
            if path.money_coefficient is None:
                unvalued.add(path.entity_id)
            else:
                known.add(path.entity_id)
    return frozenset(unvalued - known)


def legacy_copy_research_portfolio_facts(
    pin: ResearchXrayPin, value: XrayCalculation, entity_id: UUID
) -> ResearchPortfolioFacts:
    """Read one already authorized retained company bucket without recalculation."""
    if (
        type(pin) is not ResearchXrayPin
        or type(value) is not XrayCalculation
        or type(entity_id) is not UUID
    ):
        fail_validation("Canonical research exposure inputs are required.", field="portfolio_facts")
    if (
        pin.owner_id,
        pin.account_id,
        pin.snapshot_id,
        pin.input_digest,
        pin.result_digest,
        pin.reporting_currency,
        pin.valuation_at,
        pin.source_cutoff_at,
        pin.quality_evaluated_at,
        pin.policy_id,
        pin.policy_version,
        pin.method,
        pin.method_version,
        pin.numerical_profile,
        pin.schema_version,
    ) != (
        value.owner_id,
        value.account_id,
        value.snapshot_id,
        value.input_digest,
        value.content_digest,
        value.reporting_currency,
        value.valuation_at.value,
        value.source_cutoff_at.value,
        value.quality_evaluated_at.value,
        value.policy.id,
        value.policy.version,
        value.policy.method_name,
        value.policy.method_version,
        value.policy.numeric_policy,
        value.policy.schema_version,
    ):
        fail_validation("Research X-ray pin differs from its retained result.", field="pin")
    dimensions = tuple(item for item in value.dimensions if item.dimension is XrayDimension.COMPANY)
    if len(dimensions) != 1:
        fail_validation(
            "Research company coverage is absent or duplicated.", field="portfolio_facts"
        )
    dimension = dimensions[0]
    warnings = tuple(
        ResearchPortfolioWarning(
            code=item.code,
            reason=item.reason,
            source_reference_ids=item.source_reference_ids,
            path_keys=item.path_keys,
        )
        for item in value.warnings
    )
    buckets = tuple(
        item
        for item in value.exposure_buckets
        if item.dimension is XrayDimension.COMPANY and item.bucket_key == str(entity_id)
    )
    if len(buckets) > 1:
        fail_validation("Research company exposure is duplicated.", field="entity_id")
    if not buckets:
        return ResearchPortfolioFacts(
            pin=pin,
            entity_id=entity_id,
            effective_exposure=None,
            availability=XrayAvailability.UNAVAILABLE,
            reason=ResearchExposureReason.ENTITY_ABSENT_FROM_CAPTURE,
            upstream_reason=None,
            quality=QualityState.PARTIAL,
            origin=ValueOrigin.UNAVAILABLE,
            bound=XrayBound.LOWER_BOUND,
            confidence=None,
            source_reference_ids=(),
            metric_source_reference_ids=(),
            path_keys=(),
            company_coverage_complete=dimension.complete,
            positive_unresolved_below_quantum=dimension.positive_unresolved_below_quantum,
            warnings=warnings,
        )
    bucket, metric = buckets[0], buckets[0].effective
    # X-ray publishes known subtotals, including a zero lower bound when every
    # path is unvalued. Research must distinguish that from evidenced zero.
    no_known_value = entity_id in legacy_unvalued_entity_ids(value)
    availability = XrayAvailability.UNAVAILABLE if no_known_value else metric.availability
    return ResearchPortfolioFacts(
        pin=pin,
        entity_id=entity_id,
        effective_exposure=None if no_known_value else metric.value,
        availability=availability,
        reason=None
        if availability is XrayAvailability.AVAILABLE
        else ResearchExposureReason.CAPTURED_VALUE_UNAVAILABLE,
        upstream_reason=XrayReason.INCOMPLETE_VALUATION if no_known_value else metric.reason,
        quality=metric.quality,
        origin=ValueOrigin.UNAVAILABLE if no_known_value else metric.origin,
        bound=metric.bound,
        confidence=metric.confidence,
        source_reference_ids=bucket.source_reference_ids,
        metric_source_reference_ids=metric.source_reference_ids,
        path_keys=bucket.path_keys,
        company_coverage_complete=dimension.complete,
        positive_unresolved_below_quantum=dimension.positive_unresolved_below_quantum,
        warnings=warnings,
    )
