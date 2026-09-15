"""Compact paging preserves whole financial rows and rejects stale identity bindings."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from trading212_analytics.scenario import calculate_scenario, compare_scenario_results
from trading212_application import scenario_projection as projection
from trading212_application.queries import CursorCodec
from trading212_application.scenario import (
    ScenarioComparisonQuery,
    ScenarioComponentPageQuery,
    ScenarioErrorCode,
    ScenarioServiceError,
)
from trading212_application.scenario_projection import (
    RetainedScenarioResult,
    project_scenario_comparison_page,
    project_scenario_page,
    scenario_public_bytes,
)
from trading212_application.scenario_views import ScenarioComponentView
from trading212_domain.errors import DomainError
from trading212_domain.scenario_result import ScenarioCalculation
from trading212_domain.scenario_serialization import (
    canonical_scenario_bytes,
    scenario_result_digest,
)
from trading212_domain.serialization import canonical_json
from trading212_security.principals import Principal, Scope

from tests.unit.analytics.scenario_factories import content, input_for, portfolio, price, rate
from tests.unit.analytics.xray_factories import uid
from tests.unit.domain.scenario_factories import sensitivity_capture

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)
pytestmark = pytest.mark.unit


def principal() -> Principal:
    return Principal(
        principal_id="scenario-principal",
        owner_id=str(uid(1)),
        issuer="https://issuer.example.test",
        subject="scenario-owner",
        scopes=frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ}),
        authenticated_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )


def saved(
    result: ScenarioCalculation | None = None, *, run: int = 20_000
) -> RetainedScenarioResult:
    result = (
        calculate_scenario(input_for(portfolio(("60", "30", "10")), content(price(10, "-.1"))))
        if result is None
        else result
    )
    return RetainedScenarioResult(
        run_id=uid(run),
        result_id=uid(run + 1),
        account_id=result.pins.account_id,
        created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        result_digest=scenario_result_digest(result),
        calculation=result,
    )


def codec() -> CursorCodec:
    return CursorCodec(b"synthetic-scenario-cursor-key-00000", clock=lambda: NOW)


def test_all_components_are_traversable_without_changing_saved_money_or_proof() -> None:
    retained = saved()
    original = canonical_scenario_bytes(retained.calculation)
    signing = codec()
    query = ScenarioComponentPageQuery(component_limit=1)
    rows: list[ScenarioComponentView] = []
    while True:
        page = project_scenario_page(
            principal(), retained.account_id, retained, query, cursors=signing, now=NOW
        )
        assert page.view_version == "scenario_compact_v1"
        assert page.content_digest != retained.result_digest
        assert page.context.saved_result_digest == retained.result_digest
        assert (
            page.context.summary.post_value.value == retained.calculation.summary.post_value.value
        )
        assert page.components.total == 3 and len(page.components.items) == 1
        rows.extend(page.components.items)
        if page.components.next_cursor is None:
            break
        query = replace(query, component_cursor=page.components.next_cursor)
    assert [row.exposure.path_key for row in rows] == [
        row.exposure.path_key for row in retained.calculation.components
    ]
    for public, private in zip(rows, retained.calculation.components, strict=True):
        assert public.post_value.value == private.post_value.value
        assert public.post_value.quality == private.post_value.quality
        assert public.post_value.reason == private.post_value.reason
        assert public.post_value.confidence == private.post_value.confidence
        assert public.effects.price_ratio == private.effects.price_ratio
        assert public.effects.fx_ratio == private.effects.fx_ratio
    assert canonical_scenario_bytes(retained.calculation) == original


def test_candidate_preview_keeps_selected_observation_and_explicit_omission_count() -> None:
    capture = sensitivity_capture()
    result = calculate_scenario(
        input_for(portfolio(("100",), economic="EUR"), content(rate(capture, ".01")), capture)
    )
    (component,) = result.components
    (use,) = component.sensitivity_uses
    candidates = tuple(
        sorted((*use.candidate_observation_ids, *(uid(i) for i in range(1000, 1040))))
    )
    widened = replace(use, candidate_observation_ids=candidates)
    refs = tuple(uid(i) for i in range(2000, 2040))
    metric = replace(component.post_value, source_reference_ids=refs)
    result = replace(
        result, components=(replace(component, sensitivity_uses=(widened,), post_value=metric),)
    )
    retained = saved(result)
    page = project_scenario_page(
        principal(),
        retained.account_id,
        retained,
        ScenarioComponentPageQuery(),
        cursors=codec(),
        now=NOW,
    )
    public = page.components.items[0]
    projected = public.sensitivity_uses[0]
    assert projected.observation_id == use.observation_id
    assert projected.observation_id in projected.candidate_observation_ids.items
    assert len(projected.candidate_observation_ids.items) == 16
    assert projected.candidate_observation_ids.omitted_count == len(candidates) - 16
    assert projected.coefficient == Decimal("-2") and projected.shock_size == Decimal(".01")
    assert projected.effect_ratio == use.effect_ratio
    assert public.post_value.value == metric.value
    assert public.post_value.source_reference_ids.items == refs[:16]
    assert public.post_value.source_reference_ids.omitted_count == 24


@pytest.mark.parametrize(
    "changed", ["issuer", "subject", "owner", "run", "result", "digest", "limit"]
)
def test_cursor_binds_stable_principal_and_immutable_selected_result(changed: str) -> None:
    retained = saved()
    actor = principal()
    signing = codec()
    query = ScenarioComponentPageQuery(component_limit=1)
    first = project_scenario_page(
        actor, retained.account_id, retained, query, cursors=signing, now=NOW
    )
    query = replace(query, component_cursor=first.components.next_cursor)
    assert query.component_cursor is not None
    if changed == "issuer":
        actor = replace(actor, issuer="https://other.example.test")
    elif changed == "subject":
        actor = replace(actor, subject="other-subject")
    elif changed == "owner":
        actor = replace(actor, owner_id=str(uid(999)))
    elif changed == "run":
        retained = replace(retained, run_id=uid(99_000))
    elif changed == "result":
        retained = replace(retained, result_id=uid(99_001))
    elif changed == "digest":
        retained = saved(
            calculate_scenario(input_for(portfolio(("60", "30", "10")), content(price(10, "-.2"))))
        )
    else:
        query = replace(query, component_limit=2)
    with pytest.raises(ScenarioServiceError) as error:
        project_scenario_page(actor, retained.account_id, retained, query, cursors=signing, now=NOW)
    assert error.value.code is ScenarioErrorCode.CURSOR_INVALID


def test_cursor_cannot_continue_after_selected_source_lifetime_even_with_live_codec() -> None:
    retained = replace(saved(), expires_at=NOW + timedelta(seconds=20))
    query = ScenarioComponentPageQuery(component_limit=1)
    first = project_scenario_page(
        principal(), retained.account_id, retained, query, cursors=codec(), now=NOW
    )
    query = replace(query, component_cursor=first.components.next_cursor)
    assert query.component_cursor is not None
    with pytest.raises(ScenarioServiceError) as error:
        project_scenario_page(
            principal(),
            retained.account_id,
            retained,
            query,
            cursors=codec(),
            now=NOW + timedelta(seconds=20),
        )
    assert error.value.code is ScenarioErrorCode.RUN_EXPIRED


def test_cursor_follows_stable_identity_across_authenticated_token_refresh() -> None:
    retained = saved()
    actor = principal()
    query = ScenarioComponentPageQuery(component_limit=1)
    first = project_scenario_page(
        actor, retained.account_id, retained, query, cursors=codec(), now=NOW
    )
    refreshed = replace(
        actor,
        principal_id="refreshed-principal",
        authenticated_at=NOW,
        expires_at=NOW + timedelta(hours=2),
        session_id="new-authenticated-session",
    )
    continued = project_scenario_page(
        refreshed,
        retained.account_id,
        retained,
        replace(query, component_cursor=first.components.next_cursor),
        cursors=codec(),
        now=NOW,
    )
    assert continued.components.start_ordinal == 1


def test_saved_digest_mismatch_rejects_before_projection() -> None:
    retained = replace(saved(), result_digest="0" * 64)
    with pytest.raises(DomainError, match="identities differ"):
        project_scenario_page(
            principal(),
            retained.account_id,
            retained,
            ScenarioComponentPageQuery(),
            cursors=codec(),
            now=NOW,
        )


def test_utf8_budget_returns_whole_components_and_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = replace(content(), description="界" * 1024)
    retained = saved(calculate_scenario(input_for(portfolio(("60", "30", "10")), definition)))
    query = ScenarioComponentPageQuery(component_limit=3)
    signing = codec()
    full = project_scenario_page(
        principal(), retained.account_id, retained, query, cursors=signing, now=NOW
    )
    assert projection.SCENARIO_PUBLIC_PAGE_BYTES == 1_048_576
    character_count = len(canonical_json(full))
    byte_count = len(scenario_public_bytes(full))
    assert byte_count > character_count
    # A character-count implementation would accept all three rows under this budget.
    budget = (character_count + byte_count) // 2
    monkeypatch.setattr(projection, "SCENARIO_PUBLIC_PAGE_BYTES", budget)
    observed: list[str] = []
    while True:
        page = project_scenario_page(
            principal(), retained.account_id, retained, query, cursors=signing, now=NOW
        )
        assert len(scenario_public_bytes(page)) <= budget
        assert 0 < len(page.components.items) < 3
        observed.extend(row.exposure.path_key for row in page.components.items)
        if page.components.next_cursor is None:
            break
        query = replace(query, component_cursor=page.components.next_cursor)
    assert observed == [row.exposure.path_key for row in retained.calculation.components]


def test_oversized_single_component_is_explicit_failure_not_an_empty_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retained = saved(calculate_scenario(input_for(portfolio(("100",)), content())))
    query = ScenarioComponentPageQuery()
    full = project_scenario_page(
        principal(), retained.account_id, retained, query, cursors=codec(), now=NOW
    )
    monkeypatch.setattr(
        projection, "SCENARIO_PUBLIC_PAGE_BYTES", len(scenario_public_bytes(full)) - 1
    )
    with pytest.raises(ScenarioServiceError) as error:
        project_scenario_page(
            principal(), retained.account_id, retained, query, cursors=codec(), now=NOW
        )
    assert error.value.code is ScenarioErrorCode.INPUT_BOUND_EXCEEDED


def test_comparison_preserves_incompatible_sides_and_rejects_cross_resource_cursor() -> None:
    source = portfolio(("60", "30", "10"))
    left = saved(calculate_scenario(input_for(source, content(price(10, "-.1")))))
    right = saved(
        calculate_scenario(input_for(source, content(price(10, "-.2"), mode="first_order"))),
        run=30_000,
    )
    comparison = compare_scenario_results(left.calculation, right.calculation)
    query = ScenarioComparisonQuery(run_ids=(left.run_id, right.run_id), component_limit=1)
    page = project_scenario_comparison_page(
        principal(), left.account_id, left, right, comparison, query, cursors=codec(), now=NOW
    )
    assert not page.compatible
    assert page.post_value.before.value == left.calculation.summary.post_value.value
    assert page.post_value.after.value == right.calculation.summary.post_value.value
    assert page.post_value.difference.value is None
    assert page.components.items[0].before is not None
    assert page.components.items[0].after is not None
    assert page.components.next_cursor is not None
    traversal_query = query
    paths: list[tuple[str, str]] = []
    while True:
        traversed = project_scenario_comparison_page(
            principal(),
            left.account_id,
            left,
            right,
            comparison,
            traversal_query,
            cursors=codec(),
            now=NOW,
        )
        paths.extend((row.root_key, row.path_key) for row in traversed.components.items)
        assert all(row.post_value.difference.value is None for row in traversed.components.items)
        if traversed.components.next_cursor is None:
            break
        traversal_query = replace(
            traversal_query, component_cursor=traversed.components.next_cursor
        )
    assert paths == [(row.root_key, row.path_key) for row in comparison.components]
    run_query = ScenarioComponentPageQuery(
        component_limit=1, component_cursor=page.components.next_cursor
    )
    with pytest.raises(ScenarioServiceError) as error:
        project_scenario_page(
            principal(), left.account_id, left, run_query, cursors=codec(), now=NOW
        )
    assert error.value.code is ScenarioErrorCode.CURSOR_INVALID
    reversed_query = replace(
        query, run_ids=(right.run_id, left.run_id), component_cursor=page.components.next_cursor
    )
    reversed_comparison = compare_scenario_results(right.calculation, left.calculation)
    with pytest.raises(ScenarioServiceError) as error:
        project_scenario_comparison_page(
            principal(),
            left.account_id,
            right,
            left,
            reversed_comparison,
            reversed_query,
            cursors=codec(),
            now=NOW,
        )
    assert error.value.code is ScenarioErrorCode.CURSOR_INVALID


@pytest.mark.parametrize("limit", [0, 101, True])
def test_component_page_limit_is_closed_and_rejects_booleans(limit: int) -> None:
    with pytest.raises(DomainError):
        ScenarioComponentPageQuery(component_limit=limit)


def test_comparison_order_is_preserved_and_duplicate_runs_reject() -> None:
    query = ScenarioComparisonQuery(run_ids=(uid(2), uid(1)))
    assert query.run_ids == (uid(2), uid(1))
    with pytest.raises(DomainError):
        ScenarioComparisonQuery(run_ids=(uid(1), uid(1)))
