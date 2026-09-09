"""Nonfinancial projection from shared canonical X-ray records to shared app views."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from trading212_application import xray as app
from trading212_domain.xray import (
    CashRoot,
    ConcentrationThresholdPolicy,
    PositionRoot,
    XrayDimension,
)
from trading212_domain.xray_result import (
    CanonicalCommonEntity,
    CanonicalOverlapPair,
    FundComposition,
    XrayCalculation,
    XrayDisplayResidual,
    XrayExposureBucket,
    XrayHeldFund,
    XrayTerminalPath,
    XrayWarning,
)

from .xray_base import xray_error


def warning_view(value: XrayWarning) -> app.XrayWarningView:
    references = tuple(str(identifier) for identifier in value.source_reference_ids[:64])
    paths = value.path_keys[:64]
    return app.XrayWarningView(
        code=value.code,
        reason=value.reason,
        source_reference_ids=references,
        source_count=len(value.source_reference_ids),
        source_omitted_count=len(value.source_reference_ids) - len(references),
        path_keys=paths,
        path_count=len(value.path_keys),
        path_omitted_count=len(value.path_keys) - len(paths),
    )


def residual_view(value: XrayDisplayResidual) -> app.XrayResidualView:
    return app.XrayResidualView(
        key=value.key,
        value=value.value,
        currency=value.currency,
        kind=value.kind,
        consumer_key=value.consumer_key,
        child_count=value.child_count,
        parent_separately_rounded=value.parent_separately_rounded,
    )


def context_view(
    value: XrayCalculation,
    *,
    run_id: UUID,
    input_id: UUID,
    calculated_at: datetime,
    sources: tuple[app.XraySourceReferenceView, ...],
) -> app.XrayContext:
    if {item.id for item in sources} != {str(item.id) for item in value.source_dependencies} or len(
        sources
    ) != len(value.source_dependencies):
        raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
    policy = value.policy
    references: tuple[app.XrayPolicyReference, ...] = (
        app.XrayPolicyReference(kind="calculation", id=str(policy.id), version=policy.version),
        app.XrayPolicyReference(
            kind="provider_selection",
            id=str(policy.provider_selection_policy.id),
            version=policy.provider_selection_policy.version,
        ),
        app.XrayPolicyReference(
            kind="identity",
            id=str(policy.identity_policy.id),
            version=policy.identity_policy.version,
        ),
        app.XrayPolicyReference(
            kind="classification",
            id=str(policy.classification_policy.id),
            version=policy.classification_policy.version,
        ),
        app.XrayPolicyReference(
            kind="freshness",
            id=str(policy.freshness_policy.id),
            version=policy.freshness_policy.version,
        ),
        app.XrayPolicyReference(
            kind="quality", id=str(policy.quality_policy.id), version=policy.quality_policy.version
        ),
        app.XrayPolicyReference(
            kind="traversal",
            id=str(policy.traversal_policy.id),
            version=policy.traversal_policy.version,
        ),
    )
    if isinstance(policy.thresholds, ConcentrationThresholdPolicy):
        references += (
            app.XrayPolicyReference(
                kind="threshold", id=str(policy.thresholds.id), version=policy.thresholds.version
            ),
        )
    ordered_sources = tuple(sorted(sources, key=lambda source: source.id))
    return app.XrayContext(
        account_id=str(value.account_id),
        snapshot_id=str(value.snapshot_id),
        run_id=str(run_id),
        input_snapshot_id=str(input_id),
        input_digest=value.input_digest,
        content_digest=value.content_digest,
        valuation_at=value.valuation_at.value,
        source_cutoff_at=value.source_cutoff_at.value,
        reporting_currency=value.reporting_currency,
        calculated_at=calculated_at,
        quality_evaluated_at=value.quality_evaluated_at.value,
        method=app.XrayMethodView(),
        policies=references,
        sources=ordered_sources[:64],
        source_count=len(ordered_sources),
        source_omitted_count=max(0, len(ordered_sources) - 64),
        warnings=tuple(warning_view(item) for item in value.warnings[:64]),
        warning_count=len(value.warnings),
        warning_omitted_count=max(0, len(value.warnings) - 64),
        residuals=tuple(residual_view(item) for item in value.residuals[:64]),
        residual_count=len(value.residuals),
        residual_omitted_count=max(0, len(value.residuals) - 64),
    )


def exposure_view(
    value: XrayExposureBucket,
    *,
    identifier: UUID,
    name: str,
    normalized: bool,
    residuals: tuple[XrayDisplayResidual, ...],
) -> app.XrayExposureRowView:
    return app.XrayExposureRowView(
        id=str(identifier),
        dimension=value.dimension,
        bucket_key=value.bucket_key,
        name=name,
        direct=value.direct,
        indirect=value.indirect,
        effective=value.effective,
        direct_weight=value.direct_weight,
        indirect_weight=value.indirect_weight,
        absolute_weight=value.absolute_weight,
        normalized_known_weight=value.normalized_known_weight if normalized else None,
        path_count=len(value.path_keys),
        residuals=tuple(residual_view(item) for item in residuals),
        confidence=value.confidence,
        quality=value.effective.quality,
    )


def path_view(
    value: XrayTerminalPath,
    *,
    identifier: UUID,
    root: PositionRoot | CashRoot,
    name: str,
    dimension: XrayDimension,
    normalized: bool,
    sources: Mapping[UUID, app.XraySourceReferenceView],
    residuals: tuple[XrayDisplayResidual, ...],
) -> app.XrayPathRowView:
    root_key = (
        f"position:{root.position_id}"
        if isinstance(root, PositionRoot)
        else f"cash:{root.snapshot_cash_id}"
    )
    if value.root_key != root_key or any(
        identifier not in sources for identifier in value.source_reference_ids
    ):
        raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
    classification = next(
        (item for item in value.classifications if item.dimension is dimension), None
    )
    normalized_metric = next(
        (
            item.normalized_known_weight
            for item in value.dimension_weights
            if item.dimension is dimension
        ),
        None,
    )
    if normalized and normalized_metric is None:
        raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
    return app.XrayPathRowView(
        id=str(identifier),
        key=value.key,
        root_key=value.root_key,
        root=root,
        instrument_id=None if value.instrument_id is None else str(value.instrument_id),
        entity_id=None if value.entity_id is None else str(value.entity_id),
        name=name,
        explicit_cash=value.explicit_cash,
        unresolved_reason=value.unresolved_reason,
        fund_edges=value.fund_edges,
        reporting_value=value.reporting_value,
        absolute_weight=value.absolute_weight,
        relative_weight=value.relative_weight,
        normalized_known_weight=normalized_metric if normalized else None,
        classification=classification,
        identity_decision_ids=tuple(str(item) for item in value.identity_decision_ids),
        source_reference_ids=tuple(str(item) for item in value.source_reference_ids),
        sources=tuple(sources[item] for item in value.source_reference_ids),
        residuals=tuple(residual_view(item) for item in residuals),
        quality=value.quality,
        confidence=value.confidence,
    )


def held_fund_view(
    value: FundComposition,
    *,
    held: XrayHeldFund,
    name: str,
    constituent_snapshot_id: UUID | None,
    source_at: datetime | None,
) -> app.XrayHeldFundView:
    if (
        held.instrument_id != value.fund_instrument_id
        or held.composition_root_key != value.composition_root_key
    ):
        raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
    return app.XrayHeldFundView(
        instrument_id=str(value.fund_instrument_id),
        name=name,
        position_count=len(held.root_keys),
        composition_root_key=value.composition_root_key,
        constituent_snapshot_id=None
        if constituent_snapshot_id is None
        else str(constituent_snapshot_id),
        source_at=source_at,
        unit_coverage=value.coverage,
        cash_weight=value.cash_weight,
        unresolved_weight=value.unresolved_weight,
        complete=value.complete,
        quality=value.quality,
        confidence=value.confidence,
    )


def pair_view(
    value: CanonicalOverlapPair,
    *,
    identifier: UUID,
    left: app.XrayHeldFundView,
    right: app.XrayHeldFundView,
    common_entity_count: int,
) -> app.XrayOverlapPairView:
    if (
        left.instrument_id != str(value.pair.first_fund_id)
        or right.instrument_id != str(value.pair.second_fund_id)
        or left.composition_root_key != value.first_root_key
        or right.composition_root_key != value.second_root_key
    ):
        raise xray_error(app.XrayServiceErrorCode.XRAY_UNAVAILABLE)
    return app.XrayOverlapPairView(
        id=str(identifier),
        left=left,
        right=right,
        overlap=value.overlap,
        common_entity_count=common_entity_count,
    )


def common_entity_view(
    value: CanonicalCommonEntity, *, identifier: UUID, name: str
) -> app.XrayCommonEntityView:
    return app.XrayCommonEntityView(
        id=str(identifier),
        entity_id=str(value.entity_id),
        name=name,
        left_weight=value.first_weight,
        right_weight=value.second_weight,
        common_weight=value.common_weight,
    )
