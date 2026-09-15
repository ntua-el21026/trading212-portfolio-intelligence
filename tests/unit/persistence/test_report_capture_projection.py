"""Saved-path oracles, identity denial and explicit model/goal absence."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from trading212_domain import reports as r
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.report_projection_schema import (
    PROJECTION_POINT_MONEY,
    PROJECTION_TABLE_COLUMNS,
)
from trading212_domain.report_schema import validate_report_row
from trading212_domain.report_v4 import (
    ReportDocumentHeaderV4,
    ReportProofV4,
    validate_report_profile_v4,
)
from trading212_domain.values import CurrencyCode
from trading212_persistence.report_capture_projection import project_projection

from tests.unit.persistence.projection_report_factories import case, values

pytestmark = pytest.mark.unit


def test_complete_saved_variants_paths_and_every_financial_leaf_are_copied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = case()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("report capture attempted a new calculation")

    monkeypatch.setattr("trading212_analytics.projection.calculate_projection", forbidden)
    binding = project_projection(fixture.builder, fixture.captured, fixture.saved, fixture.metadata)
    assert set(fixture.builder.rows) == set(PROJECTION_TABLE_COLUMNS)
    assert binding.capture_digest == fixture.captured.input_digest
    assert binding.numerical_input_digest == fixture.captured.plan.numerical_input_digest
    assert binding.observed is None and binding.source_cutoff_at is None
    assert binding.report_context.snapshot_id != binding.run_id
    assert binding.anchor_date == fixture.captured.plan.selection.initial.modeled_anchor_date
    table = r.ReportTableKey.PROJECTION_POINTS_V1
    expected = [
        (variant.variant, path.index, index, point)
        for variant in fixture.saved.calculation.variants
        for path in variant.paths
        for index, point in enumerate(path.points)
    ]
    assert len(fixture.builder.rows[table]) == len(expected)
    for row, (variant, path, index, point) in zip(
        fixture.builder.rows[table], expected, strict=True
    ):
        cells = values(table, row)
        assert (cells["variant"].value, cells["path_index"].value, cells["point_index"].value) == (
            variant,
            path,
            index,
        )
        for field in PROJECTION_POINT_MONEY:
            assert cells[field].value == getattr(point, field)
            assert cells[field].currency == fixture.builder.selection.reporting_currency
            assert cells[field].decimal_role is r.DecimalRole.MONEY
        assert cells["funding_failed"].value is point.funding_failed
        assert cells["unpaid_positive_below_quantum"].value is point.unpaid_positive_below_quantum
    assets = r.ReportTableKey.PROJECTION_POINT_ASSETS_V1
    original_assets = [
        asset
        for variant in fixture.saved.calculation.variants
        for path in variant.paths
        for point in path.points
        for asset in point.assets
    ]
    assert [values(assets, row)["value"].value for row in fixture.builder.rows[assets]] == [
        asset.value for asset in original_assets
    ]
    goals = r.ReportTableKey.PROJECTION_GOAL_RESULTS_V1
    for row, saved_variant in zip(
        fixture.builder.rows[goals], fixture.saved.calculation.variants, strict=True
    ):
        assert saved_variant.goal is not None
        cells = values(goals, row)
        for field in (
            "probability",
            "interval_low",
            "interval_high",
            "successes",
            "mean_shortfall",
            "objective_met",
            "funding_failed_paths",
        ):
            assert cells[field].value == getattr(saved_variant.goal, field)
        context = fixture.builder.contexts[row.context_key]
        assert context.family is r.ReportFamily.GOAL and context.method_key == "goal_analysis_v1"
    quantiles = r.ReportTableKey.PROJECTION_QUANTILES_V1
    assert len(fixture.builder.rows[quantiles]) == 3 * (4 * 10 + 5)
    for row in fixture.builder.rows[quantiles]:
        cells = values(quantiles, row)
        if cells["kind"].value == "goal_shortfall":
            assert fixture.builder.contexts[row.context_key].method_key == "goal_analysis_v1"
    assert fixture.builder.deadline == fixture.metadata.expires_at


def test_absent_goal_and_model_times_are_explicit_and_never_snapshot_time() -> None:
    fixture = case(goal=False, sensitive=False)
    binding = project_projection(fixture.builder, fixture.captured, fixture.saved, fixture.metadata)
    table = r.ReportTableKey.PROJECTION_BASIS_V1
    cells = values(table, fixture.builder.rows[table][0])
    assert cells["observed_valuation_at"].value is None
    assert cells["original_source_cutoff_at"].value is None
    assert cells["original_source_cutoff_at"].reason_key is not None
    assert cells["anchor_date"].value == fixture.captured.plan.calendar.anchor_date
    assert cells["report_context_valuation_at"].value == fixture.builder.valuation_at
    assert binding.goal is None
    table = r.ReportTableKey.PROJECTION_GOAL_STATE_V1
    goal = values(table, fixture.builder.rows[table][0])
    assert goal["available"].value is False and goal["reason"].value == "no_goal_pinned"
    assert goal["automatic_goal_acceptance"].value is False
    assert fixture.builder.rows[r.ReportTableKey.PROJECTION_GOAL_RESULTS_V1] == ()
    assert fixture.builder.rows[r.ReportTableKey.PROJECTION_SOURCE_NODES_V1] == ()


def test_goal_proof_survives_omitted_goal_presentation_section() -> None:
    fixture = case(goal_section=False)
    project_projection(fixture.builder, fixture.captured, fixture.saved, fixture.metadata)
    assert len(fixture.builder.rows[r.ReportTableKey.PROJECTION_GOAL_RESULTS_V1]) == 3
    assert fixture.builder.sections[r.ReportTableKey.PROJECTION_GOAL_RESULTS_V1] is None


@pytest.mark.parametrize(
    "change", ["run", "currency", "result", "definition", "snapshot", "clock", "goal", "lifetime"]
)
def test_foreign_or_incompatible_saved_identity_denied_before_emitting_rows(change: str) -> None:
    fixture = case(goal=False)
    builder, saved, metadata = fixture.builder, fixture.saved, fixture.metadata
    if change == "run":
        saved = replace(saved, run_id=UUID(int=800))
    elif change == "currency":
        builder.selection = replace(builder.selection, reporting_currency=CurrencyCode("USD"))
    elif change == "result":
        saved = replace(saved, content_digest="a" * 64)
    elif change == "definition":
        metadata = replace(
            metadata, assumption=replace(metadata.assumption, content_digest="b" * 64)
        )
    elif change == "snapshot":
        metadata = replace(
            metadata, report_context=replace(metadata.report_context, snapshot_digest="b" * 64)
        )
    elif change == "clock":
        metadata = replace(
            metadata,
            report_context=replace(
                metadata.report_context,
                source_cutoff_at=metadata.report_context.source_cutoff_at + timedelta(seconds=1),
            ),
        )
    elif change == "goal":
        builder.selection = replace(
            builder.selection, sections=(*builder.selection.sections, r.ReportSection.GOAL)
        )
    else:
        metadata = replace(metadata, expires_at=metadata.expires_at + timedelta(seconds=1))
    with pytest.raises(DomainError):
        project_projection(builder, fixture.captured, saved, metadata)
    assert builder.rows == {}


def test_complete_table_bound_fails_before_emission_and_never_truncates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = case()
    monkeypatch.setattr(r, "MAX_REPORT_DATASET_ROWS", 5)
    with pytest.raises(DomainError) as error:
        project_projection(fixture.builder, fixture.captured, fixture.saved, fixture.metadata)
    assert error.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    assert fixture.builder.rows == {}


def test_header_rejects_omitted_last_checkpoint_and_unbound_pin() -> None:
    fixture = case()
    binding = project_projection(fixture.builder, fixture.captured, fixture.saved, fixture.metadata)
    header = ReportDocumentHeaderV4(
        selection=fixture.builder.selection,
        owner_id=fixture.builder.owner_id,
        valuation_at=fixture.builder.valuation_at,
        context_digest="0" * 64,
        document_digest="0" * 64,
        tables=fixture.builder.descriptors(),
        premium_binding=binding,
    )
    proof = ReportProofV4(contexts=tuple(fixture.builder.contexts.values()))
    validate_report_profile_v4(header, proof, tuple(fixture.builder.bindings))
    with pytest.raises(DomainError):
        replace(
            header,
            tables=tuple(
                replace(item, row_count=item.row_count - 1)
                if item.table is r.ReportTableKey.PROJECTION_POINTS_V1
                else item
                for item in header.tables
            ),
        )
    with pytest.raises(DomainError):
        validate_report_profile_v4(header, proof, tuple(fixture.builder.bindings[:-1]))


def test_closed_projection_row_labels_cannot_be_rewritten() -> None:
    fixture = case()
    project_projection(fixture.builder, fixture.captured, fixture.saved, fixture.metadata)
    table = r.ReportTableKey.PROJECTION_VARIANTS_V1
    row = fixture.builder.rows[table][0]
    with pytest.raises(DomainError):
        validate_report_row(
            table, replace(row, cells=(replace(row.cells[0], value="latest"), *row.cells[1:]))
        )
    # A stored exact zero remains available and retains monetary units.
    point = values(
        r.ReportTableKey.PROJECTION_POINTS_V1,
        fixture.builder.rows[r.ReportTableKey.PROJECTION_POINTS_V1][0],
    )
    assert point["contributions"].value == Decimal(0)
    assert point["contributions"].state is r.CellState.AVAILABLE


def test_initial_allocation_preserves_explicit_canonical_weights() -> None:
    from hashlib import sha256

    from trading212_analytics.projection import calculate_projection
    from trading212_application.projection_capture import projection_definition_digest
    from trading212_domain.projection import ProjectionAllocation, ProjectionAsset
    from trading212_domain.projection_serialization import projection_canonical_bytes
    from trading212_persistence.projection_retained_codec import pack_projection_input

    fixture = case(goal=False, sensitive=False)
    assumption = replace(
        fixture.captured.plan.assumption_version.content,
        assets=(
            ProjectionAsset(
                key="alpha",
                annual_mean_log_return=Decimal(".04"),
                annual_volatility=Decimal(".2"),
                weight=Decimal(".7"),
            ),
            ProjectionAsset(
                key="beta",
                annual_mean_log_return=Decimal(".01"),
                annual_volatility=Decimal(".1"),
                weight=Decimal(".3"),
            ),
        ),
        correlation=((Decimal(1), Decimal(0)), (Decimal(0), Decimal(1))),
    )
    version = replace(
        fixture.captured.plan.assumption_version,
        content=assumption,
        content_digest=projection_definition_digest(assumption),
    )
    plan = replace(
        fixture.captured.plan,
        assumption_version=version,
        selection=replace(
            fixture.captured.plan.selection,
            allocation=(
                ProjectionAllocation(key="beta", weight=Decimal(".3")),
                ProjectionAllocation(key="alpha", weight=Decimal(".7")),
            ),
        ),
    )
    # The numerical contract requires allocation to equal the immutable model weights.
    # Reports preserve the explicit allocation record without authorizing a new policy.
    with pytest.raises(DomainError, match="allocation"):
        replace(
            plan,
            selection=replace(
                plan.selection,
                allocation=(
                    ProjectionAllocation(key="alpha", weight=Decimal(".1")),
                    ProjectionAllocation(key="beta", weight=Decimal(".9")),
                ),
            ),
        )
    calculation = calculate_projection(plan.inputs)
    saved = replace(
        fixture.saved,
        calculation=calculation,
        content_digest=sha256(projection_canonical_bytes(calculation)).hexdigest(),
    )
    captured = replace(fixture.captured, plan=plan, stored=pack_projection_input(plan))
    metadata = replace(
        fixture.metadata,
        assumption=replace(fixture.metadata.assumption, content_digest=version.content_digest),
    )
    project_projection(fixture.builder, captured, saved, metadata)
    table = r.ReportTableKey.PROJECTION_ASSETS_V1
    rows = [values(table, row) for row in fixture.builder.rows[table]]
    assert [row["weight"].value for row in rows] == [Decimal(".7"), Decimal(".3")]
    assert [row["initial_weight"].value for row in rows] == [Decimal(".7"), Decimal(".3")]
    assert [row["initial_ordinal"].value for row in rows] == [0, 1]
