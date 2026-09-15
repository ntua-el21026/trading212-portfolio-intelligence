"""Public X-ray metrics, complete identity memberships, and pinned policy parameters."""

from collections.abc import Iterable
from uuid import UUID

from trading212_domain import reports as r
from trading212_domain import xray as d
from trading212_domain import xray_result as x

from .historical_base import digest
from .report_builder import ReportBuilder
from .report_capture_xray import XrayValue, _row


def capture_xray_semantics(
    builder: ReportBuilder,
    context: r.ReportContext,
    value: d.XrayInput,
    result: x.XrayCalculation,
) -> None:
    def put(table: r.ReportTableKey, key: str, values: dict[str, XrayValue]) -> None:
        builder.add_proof(
            r.ReportProofRelation(
                table=table,
                row=_row(builder, context, table, key, extra=values),
            )
        )

    def members(
        parent_kind: str, parent_key: str, role: str, identifiers: Iterable[str | UUID]
    ) -> None:
        for ordinal, identifier in enumerate(identifiers):
            put(
                r.ReportTableKey.XRAY_MEMBERS,
                f"{context.key}.member.{parent_kind}.{parent_key}.{role}.{ordinal}",
                {
                    "parent_kind": parent_kind,
                    "parent_key": parent_key,
                    "role": role,
                    "ordinal": ordinal,
                    "reference_key": identifier,
                },
            )

    for position in result.direct_positions:
        root = position.root
        put(
            r.ReportTableKey.XRAY_DIRECT_POSITIONS,
            f"{context.key}.direct.{root.key}",
            {
                "root_key": root.key,
                "position_id": root.position_id,
                "instrument_id": root.instrument_id,
                "listing_id": root.listing_id,
                "reporting_value": position.reporting_value,
                "absolute_weight": position.absolute_weight,
                "is_fund": position.is_fund,
            },
        )
        members("direct_position", root.key, "source", position.source_reference_ids)
    valuation_roots: tuple[d.XrayPosition | d.XrayCash, ...] = (*value.positions, *value.cash)
    for root_value in valuation_roots:
        members("root", root_value.root.key, "valuation", root_value.valuation_refs)
        members("root", root_value.root.key, "fx", root_value.fx_refs)
    members("valuation", "portfolio", "valued", value.valuation_coverage.valued_root_keys)
    members("valuation", "portfolio", "unavailable", value.valuation_coverage.unavailable_root_keys)
    members("reconciliation", "portfolio", "source", result.reconciliation.source_reference_ids)
    for held in result.held_funds:
        members("fund", str(held.instrument_id), "root", held.root_keys)
    for composition in result.fund_compositions:
        fund_key = str(composition.fund_instrument_id)
        members("composition", fund_key, "path", composition.path_keys)
        members("composition", fund_key, "source", composition.source_reference_ids)
        for entity in composition.entities:
            key = f"{fund_key}.{entity.entity_id}"
            put(
                r.ReportTableKey.XRAY_FUND_ENTITIES,
                f"{context.key}.entity.{key}",
                {
                    "fund_instrument_id": composition.fund_instrument_id,
                    "entity_id": entity.entity_id,
                    "weight": entity.weight,
                },
            )
            members("fund_entity", key, "path", entity.path_keys)
    for bucket in result.exposure_buckets:
        key = f"{bucket.dimension.value}.{bucket.bucket_key}"
        members("bucket", key, "path", bucket.path_keys)
        members("bucket", key, "source", bucket.source_reference_ids)
    for path in result.terminal_paths:
        for measure in path.dimension_weights:
            put(
                r.ReportTableKey.XRAY_PATH_WEIGHTS,
                f"{context.key}.path_weight.{path.key}.{measure.dimension.value}",
                {
                    "path_key": path.key,
                    "dimension": measure.dimension,
                    "normalized_known_weight": measure.normalized_known_weight,
                },
            )
    policy = value.policy
    put(
        r.ReportTableKey.XRAY_POLICY,
        f"{context.key}.policy",
        {
            "id": policy.id,
            "version": policy.version,
            "method_key": policy.method_name,
            "method_version": policy.method_version,
            "numeric_policy": policy.numeric_policy,
            "schema_version": policy.schema_version,
            "quality_evaluated_at": result.quality_evaluated_at,
            "valuation_complete": value.valuation_coverage.complete,
            "threshold_state": policy.thresholds.state,
        },
    )
    components: tuple[
        tuple[
            str,
            d.XrayProviderSelectionPolicy
            | d.XrayIdentityPolicy
            | d.XrayClassificationPolicy
            | d.XrayFreshnessPolicy
            | d.XrayQualityPolicy
            | d.XrayTraversalPolicy,
        ],
        ...,
    ] = (
        ("provider_selection", policy.provider_selection_policy),
        ("identity", policy.identity_policy),
        ("classification", policy.classification_policy),
        ("freshness", policy.freshness_policy),
        ("quality", policy.quality_policy),
        ("traversal", policy.traversal_policy),
    )
    for kind, component in components:
        rule: str | None = None
        secondary: str | None = None
        age: int | None = None
        basis: str | None = None
        if isinstance(component, d.XrayProviderSelectionPolicy):
            rule, secondary = component.revision_rule, component.gap_rule
        elif isinstance(component, d.XrayFreshnessPolicy):
            age, basis = component.stale_after_seconds, component.evaluation_basis
        else:
            rule = component.rule
        put(
            r.ReportTableKey.XRAY_POLICY_COMPONENTS,
            f"{context.key}.policy.{kind}",
            {
                "kind": kind,
                "id": component.id,
                "version": component.version,
                "content_digest": digest(component),
                "rule": rule,
                "secondary_rule": secondary,
                "stale_after_seconds": age,
                "evaluation_basis": basis,
            },
        )
    members(
        "policy",
        str(policy.provider_selection_policy.id),
        "provider_order",
        policy.provider_selection_policy.provider_order,
    )
    for name in (
        "positions",
        "currencies",
        "constituent_snapshots",
        "constituent_rows",
        "identity_classification_rows",
        "selected_uses",
        "canonical_bytes",
        "singleton_bytes",
    ):
        put(
            r.ReportTableKey.XRAY_POLICY_LIMITS,
            f"{context.key}.policy.limit.{name}",
            {
                "key": name,
                "value": getattr(policy.limits, name),
            },
        )
    for name in (
        "max_fund_edges",
        "max_visited_paths",
        "max_identity_decisions",
        "max_source_references",
    ):
        put(
            r.ReportTableKey.XRAY_POLICY_LIMITS,
            f"{context.key}.policy.traversal.{name}",
            {
                "key": name,
                "value": getattr(policy.traversal_policy, name),
            },
        )
    for taxonomy in policy.taxonomy_versions:
        put(
            r.ReportTableKey.XRAY_TAXONOMIES,
            f"{context.key}.taxonomy.{taxonomy.dimension.value}",
            {
                "dimension": taxonomy.dimension,
                "taxonomy_id": taxonomy.taxonomy_id,
                "version": taxonomy.version,
                "key": taxonomy.key,
            },
        )
    threshold = policy.thresholds
    if isinstance(threshold, d.ConcentrationThresholdPolicy):
        for metric, limit, comparison in (
            ("top1", threshold.top1_limit, threshold.top1_comparison),
            ("top5", threshold.top5_limit, threshold.top5_comparison),
            ("hhi", threshold.hhi_limit, threshold.hhi_comparison),
        ):
            put(
                r.ReportTableKey.XRAY_THRESHOLD_POLICY,
                f"{context.key}.threshold.{metric}",
                {
                    "metric": metric,
                    "limit": limit,
                    "comparison": comparison,
                    "policy_id": threshold.id,
                    "policy_version": threshold.version,
                    "source_reference_id": threshold.source_reference_id,
                },
            )
