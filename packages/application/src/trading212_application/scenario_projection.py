"""Compact immutable scenario pages after caller authorization and source-rights checks.

These pure helpers do not authenticate a Principal or grant access to retained data.
The service must authorize the current principal and every selected source before
loading results, parsing cursors, projecting data or handling conditional responses.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from datetime import datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from trading212_domain.errors import fail_validation
from trading212_domain.scenario import MAX_SCENARIO_COMPONENTS
from trading212_domain.scenario_result import (
    ScenarioCalculation,
    ScenarioChannelEffects,
    ScenarioClassificationFact,
    ScenarioComparison,
    ScenarioComponent,
    ScenarioCurrencyFact,
    ScenarioDiagnostic,
    ScenarioMetricDelta,
    ScenarioMoneyMetric,
    ScenarioPartitionSummary,
    ScenarioReplayChange,
    ScenarioSensitivityUse,
    ScenarioSubjectFact,
    ScenarioTerminalExposure,
)
from trading212_domain.scenario_serialization import scenario_result_digest
from trading212_domain.serialization import canonical_json
from trading212_domain.values import require_utc
from trading212_security.principals import Principal

from . import scenario_views as v
from .queries import CursorCodec, CursorValidationError
from .scenario import (
    ScenarioComparisonQuery,
    ScenarioComponentPageQuery,
    ScenarioErrorCode,
    ScenarioServiceError,
)

SCENARIO_PREVIEW_LIMIT = 16
SCENARIO_PUBLIC_PAGE_BYTES = 1_048_576
_RUN_RESOURCE: Literal["scenario_components_v1"] = "scenario_components_v1"
_COMPARISON_RESOURCE: Literal["scenario_comparison_components_v1"] = (
    "scenario_comparison_components_v1"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RetainedScenarioResult:
    """Private projection input from a currently authorized immutable succeeded run."""

    run_id: UUID
    result_id: UUID
    account_id: UUID
    created_at: datetime
    expires_at: datetime
    result_digest: str
    calculation: ScenarioCalculation


def _preview[Item](items: tuple[Item, ...]) -> v.ScenarioPreview[Item]:
    return v.ScenarioPreview(
        items=items[:SCENARIO_PREVIEW_LIMIT],
        omitted_count=max(0, len(items) - SCENARIO_PREVIEW_LIMIT),
    )


def _money(value: ScenarioMoneyMetric) -> v.ScenarioMoneyView:
    return v.ScenarioMoneyView(
        value=value.value,
        quality=value.quality,
        reason=value.reason,
        confidence=value.confidence,
        source_reference_ids=_preview(value.source_reference_ids),
    )


def _subject(value: ScenarioSubjectFact) -> v.ScenarioSubjectView:
    return v.ScenarioSubjectView(
        dimension=value.dimension,
        state=value.state,
        subject_id=value.subject_id,
        reason=value.reason,
        upstream_reason=value.upstream_reason,
        identity_decision_ids=_preview(value.identity_decision_ids),
        source_reference_ids=_preview(value.source_reference_ids),
    )


def _classification(value: ScenarioClassificationFact) -> v.ScenarioClassificationView:
    return v.ScenarioClassificationView(
        dimension=value.dimension,
        state=value.state,
        taxonomy_id=value.taxonomy_id,
        taxonomy_version=value.taxonomy_version,
        bucket_key=value.bucket_key,
        decision_key=value.decision_key,
        assignment_ids=_preview(value.assignment_ids),
        evidence_ids=_preview(value.evidence_ids),
        source_reference_ids=_preview(value.source_reference_ids),
        reason=value.reason,
        upstream_reason=value.upstream_reason,
        confidence=value.confidence,
    )


def _currency(value: ScenarioCurrencyFact) -> v.ScenarioCurrencyView:
    return v.ScenarioCurrencyView(
        state=value.state,
        currency=value.currency,
        basis=value.basis,
        decision_key=value.decision_key,
        taxonomy_id=value.taxonomy_id,
        taxonomy_version=value.taxonomy_version,
        cash_id=value.cash_id,
        candidate_id=value.candidate_id,
        holding_id=value.holding_id,
        assignment_ids=_preview(value.assignment_ids),
        evidence_ids=_preview(value.evidence_ids),
        source_reference_ids=_preview(value.source_reference_ids),
        reason=value.reason,
        upstream_reason=value.upstream_reason,
    )


def _exposure(value: ScenarioTerminalExposure) -> v.ScenarioExposureView:
    return v.ScenarioExposureView(
        path_key=value.path_key,
        root_key=value.root_key,
        root_kind=value.root_kind,
        position_id=value.position_id,
        snapshot_cash_id=value.snapshot_cash_id,
        root_instrument_id=value.root_instrument_id,
        explicit_cash=value.explicit_cash,
        instrument=_subject(value.instrument),
        entity=_subject(value.entity),
        sector=_classification(value.sector),
        region=_classification(value.region),
        economic_currency=_currency(value.economic_currency),
        pre_value=_money(value.pre_value),
        quality=value.quality,
        confidence=value.confidence,
        upstream_reason=value.upstream_reason,
        source_reference_ids=_preview(value.source_reference_ids),
    )


def _sensitivity(value: ScenarioSensitivityUse) -> v.ScenarioSensitivityView:
    candidates = _preview(value.candidate_observation_ids)
    if value.observation_id is not None and value.observation_id not in candidates.items:
        # The selected witness is mandatory even when it lies beyond the sampled prefix.
        candidates = replace(candidates, items=(*candidates.items[:-1], value.observation_id))
    return v.ScenarioSensitivityView(
        rule_key=value.rule_key,
        driver_id=value.driver.driver_id,
        driver_definition_version_id=value.driver.definition_version_id,
        driver_definition_digest=value.driver.definition_digest,
        driver_kind=value.driver.kind,
        shock_unit=value.driver.shock_unit,
        driver_evidence_reference_ids=_preview(value.driver.evidence_reference_ids),
        version_id=value.version_id,
        candidate_observation_ids=candidates,
        observation_id=value.observation_id,
        coefficient=value.coefficient,
        shock_size=value.shock_size,
        effect_ratio=value.effect_ratio,
        reason=value.reason,
    )


def _effects(value: ScenarioChannelEffects) -> v.ScenarioEffectsView:
    return v.ScenarioEffectsView(
        price_ratio=value.price_ratio,
        factor_ratio=value.factor_ratio,
        fx_ratio=value.fx_ratio,
        price=_money(value.price),
        factor=_money(value.factor),
        fx=_money(value.fx),
        interaction=_money(value.interaction),
    )


def _diagnostic(value: ScenarioDiagnostic) -> v.ScenarioDiagnosticView:
    return v.ScenarioDiagnosticView(
        key=value.key,
        reason=value.reason,
        path_key=value.path_key,
        rule_key=value.rule_key,
        upstream_xray_reason=value.upstream_xray_reason,
        upstream_historical_reason=value.upstream_historical_reason,
        source_reference_ids=_preview(value.source_reference_ids),
        source_use_keys=_preview(value.source_use_keys),
    )


def _diagnostics(
    values: tuple[ScenarioDiagnostic, ...],
) -> v.ScenarioPreview[v.ScenarioDiagnosticView]:
    return v.ScenarioPreview(
        items=tuple(_diagnostic(value) for value in values[:SCENARIO_PREVIEW_LIMIT]),
        omitted_count=max(0, len(values) - SCENARIO_PREVIEW_LIMIT),
    )


def _replay_change(value: ScenarioReplayChange | None) -> v.ScenarioReplayChangeView | None:
    if value is None:
        return None
    return v.ScenarioReplayChangeView(
        path_key=value.path_key,
        local_return=value.local_return,
        fx_return=value.fx_return,
        reporting_return=value.reporting_return,
        basis=value.basis,
        source_use_keys=_preview(value.source_use_keys),
        conversion_keys=_preview(value.conversion_keys),
    )


def _component(
    value: ScenarioComponent, replay: ScenarioReplayChange | None
) -> v.ScenarioComponentView:
    if len(value.sensitivity_uses) > 128:
        raise ScenarioServiceError(ScenarioErrorCode.INPUT_BOUND_EXCEEDED)
    return v.ScenarioComponentView(
        exposure=_exposure(value.exposure),
        partition=value.partition,
        winning_price_rule_key=value.winning_price_rule_key,
        matching_exclusion_keys=value.matching_exclusion_keys,
        uncertain_rule_keys=value.uncertain_rule_keys,
        sensitivity_uses=tuple(_sensitivity(item) for item in value.sensitivity_uses),
        effects=_effects(value.effects),
        post_value=_money(value.post_value),
        impact=_money(value.impact),
        rounding_residual=_money(value.rounding_residual),
        money_basis=value.money_basis,
        diagnostic_keys=_preview(value.diagnostic_keys),
        replay_change=_replay_change(replay),
    )


def _summary(value: ScenarioPartitionSummary) -> v.ScenarioSummaryView:
    return v.ScenarioSummaryView(
        terminal_pre_value=_money(value.terminal_pre_value),
        covered_pre_value=_money(value.covered_pre_value),
        uncovered_pre_value=_money(value.uncovered_pre_value),
        excluded_pre_value=_money(value.excluded_pre_value),
        covered_count=value.covered_count,
        uncovered_count=value.uncovered_count,
        excluded_count=value.excluded_count,
        missing_pre_value_count=value.missing_pre_value_count,
        uncertain_money_count=value.uncertain_money_count,
        covered_post_value=_money(value.covered_post_value),
        excluded_post_value=_money(value.excluded_post_value),
        provably_unchanged_uncovered_value=_money(value.provably_unchanged_uncovered_value),
        post_value=_money(value.post_value),
        impact=_money(value.impact),
        effects=_effects(value.effects),
        rounding_residual=_money(value.rounding_residual),
        component_sum_residual=_money(value.component_sum_residual),
    )


def _context(retained: RetainedScenarioResult) -> v.ScenarioResultContextView:
    value = retained.calculation
    replay = value.replay
    replay_view = None
    if replay is not None:
        context = replay.context
        replay_view = v.ScenarioReplayContextView(
            selection=replay.selection,
            input_digest=context.input_digest,
            window=context.window,
            method=context.method,
            primitive_methods=context.primitive_methods,
            source_policy_version=context.source_policy_version,
            accounting_policy_version=context.accounting_policy_version,
            coverage=context.coverage,
            quality=context.quality,
            availability=context.availability,
            reconstruction=context.reconstruction,
            schema_version=context.schema_version,
            holdings_evidence_at=replay.holdings_evidence_at,
            holdings_knowledge_cutoff_at=replay.holdings_knowledge_cutoff_at,
            change_count=len(replay.changes),
            source_use_count=len(replay.source_uses),
            conversion_count=len(replay.conversions),
            source_reference_ids=_preview(tuple(row.id for row in context.sources)),
            warnings=v.ScenarioPreview(
                items=tuple(
                    v.ScenarioHistoricalWarningView(
                        reason_code=row.reason_code,
                        coverage_key=row.coverage_key,
                        reference_ids=_preview(row.reference_ids),
                    )
                    for row in context.warnings[:SCENARIO_PREVIEW_LIMIT]
                ),
                omitted_count=max(0, len(context.warnings) - SCENARIO_PREVIEW_LIMIT),
            ),
            assumptions=context.assumptions,
            diagnostics=_diagnostics(replay.diagnostics),
        )
    return v.ScenarioResultContextView(
        run_id=retained.run_id,
        result_id=retained.result_id,
        saved_result_digest=retained.result_digest,
        input_digest=value.input_digest,
        pins=value.pins,
        definition=value.definition,
        valuation_at=value.valuation_at,
        summary=_summary(value.summary),
        upstream_portfolio_value=_money(value.upstream_portfolio_value),
        upstream_partition_difference=_money(value.upstream_partition_difference),
        upstream_residual_keys=_preview(value.upstream_residual_keys),
        replay=replay_view,
        diagnostics=_diagnostics(value.diagnostics),
        assumptions=value.assumptions,
        sensitivity_source_row_count=value.sensitivity_source_row_count,
        method_version=value.method_version,
        schema_version=value.schema_version,
        numerical_profile=value.numerical_profile,
    )


def _delta(value: ScenarioMetricDelta) -> v.ScenarioDeltaView:
    return v.ScenarioDeltaView(
        before=_money(value.before), after=_money(value.after), difference=_money(value.difference)
    )


def _checked(retained: RetainedScenarioResult, account_id: UUID, now: datetime) -> None:
    for identifier in (retained.run_id, retained.result_id, retained.account_id, account_id):
        if type(identifier) is not UUID:
            fail_validation("Canonical retained scenario identities are required.")
    require_utc(retained.created_at)
    require_utc(retained.expires_at)
    if retained.expires_at <= now:
        raise ScenarioServiceError(ScenarioErrorCode.RUN_EXPIRED)
    if (
        retained.created_at > now
        or retained.created_at >= retained.expires_at
        or retained.account_id != account_id
        or retained.calculation.pins.account_id != account_id
        or scenario_result_digest(retained.calculation) != retained.result_digest
    ):
        fail_validation("Retained scenario result identities differ.")


def _binding(
    principal: Principal,
    account_id: UUID,
    retained: tuple[RetainedScenarioResult, ...],
    query: ScenarioComponentPageQuery,
    resource: str,
) -> tuple[str, datetime]:
    expiry = min(item.expires_at for item in retained)
    binding = canonical_json(
        {
            "issuer": principal.issuer,
            "subject": principal.subject,
            "owner_id": principal.owner_id,
            "account_id": account_id,
            "runs": tuple((item.run_id, item.result_id, item.result_digest) for item in retained),
            "view": v.SCENARIO_PUBLIC_VIEW_VERSION,
            "resource": resource,
            "limit": query.component_limit,
            "expires_at": expiry,
        }
    )
    return binding, expiry


def _start(
    codec: CursorCodec,
    query: ScenarioComponentPageQuery,
    *,
    resource: str,
    binding: str,
    expires_at: datetime,
    now: datetime,
    total: int,
) -> tuple[int, datetime]:
    if expires_at <= now:
        raise ScenarioServiceError(ScenarioErrorCode.RUN_EXPIRED)
    if query.component_cursor is None:
        return 0, now
    try:
        cutoff, key = codec.decode(
            query.component_cursor, resource=resource, binding=binding, key_size=2
        )
        ordinal = int(key[0])
        if (
            str(ordinal) != key[0]
            or not 0 < ordinal < total
            or key[1] != expires_at.isoformat()
            or cutoff > now
            or cutoff >= expires_at
        ):
            raise CursorValidationError("invalid cursor")
        return ordinal, cutoff
    except (CursorValidationError, ValueError) as exc:
        raise ScenarioServiceError(ScenarioErrorCode.CURSOR_INVALID) from exc


type _PublicPage = v.ScenarioResultPage | v.ScenarioComparisonPage


def scenario_public_bytes(value: _PublicPage) -> bytes:
    """Serialize only the distinct public page types, with exact UTF-8 byte accounting."""
    if type(value) not in (v.ScenarioResultPage, v.ScenarioComparisonPage):
        fail_validation("A compact scenario public page is required.")
    return canonical_json(value).encode("utf-8")


def _signed[Page: _PublicPage](page: Page) -> Page:
    content = {
        field.name: getattr(page, field.name)
        for field in fields(page)
        if field.name != "content_digest"
    }
    digest = sha256(
        b"t212pi.scenario.public.compact.v1\0" + canonical_json(content).encode("utf-8")
    ).hexdigest()
    return replace(page, content_digest=digest)


def _page[Item, Page: _PublicPage](
    *,
    codec: CursorCodec,
    query: ScenarioComponentPageQuery,
    resource: Literal["scenario_components_v1", "scenario_comparison_components_v1"],
    binding: str,
    expires_at: datetime,
    now: datetime,
    total: int,
    project: Callable[[int], Item],
    build: Callable[[v.ScenarioComponentPage[Item]], Page],
) -> Page:
    start, cutoff = _start(
        codec,
        query,
        resource=resource,
        binding=binding,
        expires_at=expires_at,
        now=now,
        total=total,
    )

    def make(items: tuple[Item, ...], ordinal: int) -> Page:
        cursor = None
        if ordinal < total:
            cursor = codec.encode(
                resource=resource,
                binding=binding,
                read_cutoff=cutoff,
                key=(str(ordinal), expires_at.isoformat()),
            )
            if len(cursor) > 2048:
                raise ScenarioServiceError(ScenarioErrorCode.INPUT_BOUND_EXCEEDED)
        return _signed(
            build(
                v.ScenarioComponentPage(
                    items=items,
                    next_cursor=cursor,
                    component_limit=query.component_limit,
                    total=total,
                    start_ordinal=start,
                )
            )
        )

    selected: tuple[Item, ...] = ()
    result = make(selected, start)
    if len(scenario_public_bytes(result)) > SCENARIO_PUBLIC_PAGE_BYTES:
        raise ScenarioServiceError(ScenarioErrorCode.INPUT_BOUND_EXCEEDED)
    for ordinal in range(start, min(total, start + query.component_limit)):
        candidate = (*selected, project(ordinal))
        next_result = make(candidate, ordinal + 1)
        if len(scenario_public_bytes(next_result)) > SCENARIO_PUBLIC_PAGE_BYTES:
            if not selected:
                raise ScenarioServiceError(ScenarioErrorCode.INPUT_BOUND_EXCEEDED)
            break
        selected, result = candidate, next_result
    return result


def project_scenario_page(
    principal: Principal,
    account_id: UUID,
    retained: RetainedScenarioResult,
    query: ScenarioComponentPageQuery,
    *,
    cursors: CursorCodec,
    now: datetime,
) -> v.ScenarioResultPage:
    """Page an already authorized saved result without altering its financial records."""
    require_utc(now)
    _checked(retained, account_id, now)
    context = _context(retained)
    components = tuple(
        sorted(retained.calculation.components, key=lambda item: item.exposure.path_key)
    )
    replay = retained.calculation.replay
    changes = {} if replay is None else {item.path_key: item for item in replay.changes}
    if replay is not None and set(changes) != {item.exposure.path_key for item in components}:
        fail_validation("Retained scenario replay component inventory differs.")
    binding, expiry = _binding(principal, account_id, (retained,), query, _RUN_RESOURCE)
    return _page(
        codec=cursors,
        query=query,
        resource=_RUN_RESOURCE,
        binding=binding,
        expires_at=expiry,
        now=now,
        total=len(components),
        project=lambda ordinal: _component(
            components[ordinal], changes.get(components[ordinal].exposure.path_key)
        ),
        build=lambda page: v.ScenarioResultPage(
            context=context, components=page, content_digest="0" * 64
        ),
    )


def project_scenario_comparison_page(
    principal: Principal,
    account_id: UUID,
    before: RetainedScenarioResult,
    after: RetainedScenarioResult,
    comparison: ScenarioComparison,
    query: ScenarioComparisonQuery,
    *,
    cursors: CursorCodec,
    now: datetime,
) -> v.ScenarioComparisonPage:
    """Page saved side values/deltas; this never recalculates either scenario."""
    require_utc(now)
    _checked(before, account_id, now)
    _checked(after, account_id, now)
    if query.run_ids != (before.run_id, after.run_id) or (
        comparison.left_result_digest != before.result_digest
        or comparison.right_result_digest != after.result_digest
    ):
        fail_validation("Scenario comparison result identities differ.")
    left = {
        (item.exposure.root_key, item.exposure.path_key): item
        for item in before.calculation.components
    }
    right = {
        (item.exposure.root_key, item.exposure.path_key): item
        for item in after.calculation.components
    }
    deltas = {(item.root_key, item.path_key): item for item in comparison.components}
    keys = tuple(sorted(set(left) | set(right)))
    if len(keys) > MAX_SCENARIO_COMPONENTS:
        raise ScenarioServiceError(ScenarioErrorCode.INPUT_BOUND_EXCEEDED)
    if set(deltas) != set(keys):
        fail_validation("Scenario comparison component inventory differs.")
    if (
        comparison.post_value.before != before.calculation.summary.post_value
        or comparison.post_value.after != after.calculation.summary.post_value
        or comparison.impact.before != before.calculation.summary.impact
        or comparison.impact.after != after.calculation.summary.impact
    ):
        fail_validation("Scenario comparison retained summary values differ.")
    for key in keys:
        for component, post, impact in (
            (left.get(key), deltas[key].post_value.before, deltas[key].impact.before),
            (right.get(key), deltas[key].post_value.after, deltas[key].impact.after),
        ):
            if component is not None and (
                post != component.post_value or impact != component.impact
            ):
                fail_validation("Scenario comparison retained component values differ.")
            if component is None and (post.value is not None or impact.value is not None):
                fail_validation("An absent scenario component cannot carry comparison money.")
    left_replay, right_replay = before.calculation.replay, after.calculation.replay
    left_changes = {} if left_replay is None else {row.path_key: row for row in left_replay.changes}
    right_changes = (
        {} if right_replay is None else {row.path_key: row for row in right_replay.changes}
    )
    for result, changes in ((before.calculation, left_changes), (after.calculation, right_changes)):
        if result.replay is not None and set(changes) != {
            row.exposure.path_key for row in result.components
        }:
            fail_validation("Retained scenario replay component inventory differs.")
    left_context, right_context = _context(before), _context(after)

    def project(ordinal: int) -> v.ScenarioComparisonComponentView:
        key = keys[ordinal]
        left_component, right_component = left.get(key), right.get(key)
        value = deltas[key]
        return v.ScenarioComparisonComponentView(
            root_key=key[0],
            path_key=key[1],
            before=None
            if left_component is None
            else _component(left_component, left_changes.get(key[1])),
            after=None
            if right_component is None
            else _component(right_component, right_changes.get(key[1])),
            post_value=_delta(value.post_value),
            impact=_delta(value.impact),
        )

    binding, expiry = _binding(principal, account_id, (before, after), query, _COMPARISON_RESOURCE)
    return _page(
        codec=cursors,
        query=query,
        resource=_COMPARISON_RESOURCE,
        binding=binding,
        expires_at=expiry,
        now=now,
        total=len(keys),
        project=project,
        build=lambda page: v.ScenarioComparisonPage(
            before=left_context,
            after=right_context,
            compatible=comparison.compatible,
            mismatches=comparison.mismatches,
            post_value=_delta(comparison.post_value),
            impact=_delta(comparison.impact),
            components=page,
            content_digest="0" * 64,
        ),
    )
