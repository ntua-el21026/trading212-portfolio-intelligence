"""Copied canonical X-ray exposures, never figures inferred from source prose."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from .enums import QualityState, ValueOrigin
from .errors import fail_validation
from .research import (
    MAX_RESEARCH_EXPOSURE_PATHS,
    ResearchExposureReason,
    ResearchRecord,
    inert_research_text,
    research_bound,
    research_unique,
)
from .values import CurrencyCode, Money
from .xray import XrayAvailability, XrayBound, XrayDimension, XrayReason, XrayWarningCode
from .xray_result import XrayCalculation


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchXrayPin(ResearchRecord):
    owner_id: UUID
    account_id: UUID
    run_id: UUID
    snapshot_id: UUID
    input_digest: str
    result_digest: str
    reporting_currency: CurrencyCode
    valuation_at: datetime
    source_cutoff_at: datetime
    quality_evaluated_at: datetime
    policy_id: UUID
    policy_version: str
    method: Literal["xray_v1"] = "xray_v1"
    method_version: Literal["1.1.0"] = "1.1.0"
    numerical_profile: Literal["xray_decimal256_exact_q18_v1"] = "xray_decimal256_exact_q18_v1"
    schema_version: Literal["1"] = "1"


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchPortfolioWarning(ResearchRecord):
    code: XrayWarningCode
    reason: XrayReason | None
    source_reference_ids: tuple[UUID, ...]
    path_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        research_unique(self.source_reference_ids, "warning.source_reference_ids")
        research_unique(self.path_keys, "warning.path_keys")
        for path in self.path_keys:
            research_bound(len(path) <= 1024, "warning.path_keys")
            if inert_research_text(path) != path:
                fail_validation(
                    "Research warning path is not canonical.", field="warning.path_keys"
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchPortfolioFacts(ResearchRecord):
    pin: ResearchXrayPin
    entity_id: UUID
    effective_exposure: Money | None
    availability: XrayAvailability
    reason: ResearchExposureReason | None
    upstream_reason: XrayReason | None
    quality: QualityState
    origin: ValueOrigin
    bound: XrayBound
    confidence: Decimal | None
    source_reference_ids: tuple[UUID, ...]
    metric_source_reference_ids: tuple[UUID, ...]
    path_keys: tuple[str, ...]
    company_coverage_complete: bool
    positive_unresolved_below_quantum: bool
    warnings: tuple[ResearchPortfolioWarning, ...]
    content_type: Literal["portfolio_facts"] = "portfolio_facts"
    schema_version: Literal["1.0.0"] = "1.0.0"

    def __post_init__(self) -> None:
        ResearchRecord.__post_init__(self)
        available = self.availability is XrayAvailability.AVAILABLE
        if available != (self.effective_exposure is not None and self.reason is None) or (
            not available and (self.effective_exposure is not None or self.reason is None)
        ):
            fail_validation("Research exposure availability differs.", field="effective_exposure")
        if (
            self.effective_exposure is not None
            and self.effective_exposure.currency != self.pin.reporting_currency
        ):
            fail_validation("Research exposure currency differs.", field="effective_exposure")
        if self.confidence is not None and not Decimal(0) <= self.confidence <= Decimal(1):
            fail_validation("Research confidence exceeds its bound.", field="confidence")
        research_bound(len(self.path_keys) <= MAX_RESEARCH_EXPOSURE_PATHS, "path_keys")
        for path in self.path_keys:
            research_bound(len(path) <= 1024, "path_keys")
            if inert_research_text(path) != path:
                fail_validation("Research path identity is not canonical.", field="path_keys")
        research_unique(self.path_keys, "path_keys")
        research_unique(self.source_reference_ids, "source_reference_ids")
        research_unique(self.metric_source_reference_ids, "metric_source_reference_ids")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchSynthesisUnavailable(ResearchRecord):
    reason: Literal["disabled", "not_configured", "source_unavailable"] = "disabled"
    availability: Literal["unavailable"] = "unavailable"
    content_type: Literal["optional_synthesis"] = "optional_synthesis"


def copy_research_portfolio_facts(
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
    return ResearchPortfolioFacts(
        pin=pin,
        entity_id=entity_id,
        effective_exposure=metric.value,
        availability=metric.availability,
        reason=None
        if metric.availability is XrayAvailability.AVAILABLE
        else ResearchExposureReason.CAPTURED_VALUE_UNAVAILABLE,
        upstream_reason=metric.reason,
        quality=metric.quality,
        origin=metric.origin,
        bound=metric.bound,
        confidence=metric.confidence,
        source_reference_ids=bucket.source_reference_ids,
        metric_source_reference_ids=metric.source_reference_ids,
        path_keys=bucket.path_keys,
        company_coverage_complete=dimension.complete,
        positive_unresolved_below_quantum=dimension.positive_unresolved_below_quantum,
        warnings=warnings,
    )
