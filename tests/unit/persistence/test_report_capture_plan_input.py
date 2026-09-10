"""Saved planning operands retain exact original currencies, options and source versions."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest
from trading212_analytics.planning import calculate_contribution_plan
from trading212_application.reports import ReportServiceError
from trading212_domain import planning as d
from trading212_domain import reports as r
from trading212_domain import targets as t
from trading212_domain.enums import QualityState
from trading212_domain.planning_serialization import (
    contribution_plan_result_digest,
    planning_input_digest,
)
from trading212_domain.report_manifest import decode_report_chunk
from trading212_domain.report_schema import table_schema
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.planning_models import (
    ContributionPlanRequestModel,
    ContributionPlanResultModel,
)
from trading212_persistence.report_builder import ReportBuilder
from trading212_persistence.report_capture_plan_input import capture_plan_input
from trading212_persistence.report_capture_planning import _capture_plan, _constraint_row

from tests.unit.analytics.planning_factories import AT, EUR, planning_input, uid
from tests.unit.persistence.test_report_capture_builder import Sink

pytestmark = pytest.mark.unit


def fixture(value: d.PlanningInput) -> tuple[ReportBuilder, Sink, r.ReportContext]:
    selection = r.ReportSelection(
        account_id=UUID(value.valuation.account_id),
        snapshot_id=UUID(value.valuation.snapshot_id),
        start_date=AT.date(),
        end_date=AT.date(),
        source_cutoff_at=AT,
        reporting_currency=EUR,
        report_type=r.ReportType.CONTRIBUTION_PLAN,
        sections=(
            r.ReportSection.OVERVIEW,
            r.ReportSection.TARGETS,
            r.ReportSection.CONTRIBUTION_PLAN,
            r.ReportSection.QUALITY,
        ),
        formats=(r.ReportFormat.JSON,),
        target_version_id=UUID(value.target_version_id),
        plan_revision_id=UUID(int=6),
    )
    context = r.ReportContext(
        key="context.operands",
        family=r.ReportFamily.PLANNING,
        method_key=d.PLAN_METHOD,
        method_version=value.method_version,
        valuation_at=AT,
        source_cutoff_at=AT,
        quality=QualityState.FRESH,
        provenance_set_key="sources.operands",
        coverage_set_key="coverage.operands",
        note_set_key="notes.operands",
    )
    sink = Sink()
    builder = ReportBuilder(selection, owner_id=UUID(int=9), valuation_at=AT, sink=sink)
    builder.add_context(context)
    return builder, sink, context


def rows(sink: Sink, table: r.ReportTableKey) -> list[dict[str, r.ReportCell]]:
    result: list[dict[str, r.ReportCell]] = []
    for chunk in sink.chunks:
        assert decode_report_chunk(chunk.canonical_bytes) == chunk
        if chunk.table is table:
            result.extend(
                dict(
                    zip(
                        (column.key for column in table_schema(table).columns),
                        row.cells,
                        strict=True,
                    )
                )
                for row in chunk.rows
            )
    return result


def test_saved_original_money_fx_and_every_option_are_typed_and_hash_bound() -> None:
    value = planning_input(grouped=True, mode=d.PlanningMode.RESTRICTED)
    source = d.PlanningSource(
        "provider_fx_observation", uid(900), "f" * 64, "broker-fixing-v7", AT, AT
    )
    fx = d.PlanningFxRate(source, CurrencyCode("USD"), EUR, Decimal("0.8"))
    valuation = replace(
        value.valuation,
        positions=(
            replace(
                value.valuation.positions[0],
                value=Money(Decimal("62.50"), CurrencyCode("USD")),
                fx=fx,
            ),
            replace(value.valuation.positions[1], value=None, quality=QualityState.PARTIAL),
        ),
        cash_components=(
            d.ValuationCash(Money(Decimal("3.125"), CurrencyCode("USD")), QualityState.STALE, fx),
        ),
        sources=(*value.valuation.sources, source),
        missing_inputs=("missing.position.value",),
        coverage_complete=False,
    )
    options = replace(
        value.options,
        coverage_policy=d.CoveragePolicy.ALLOW_DEGRADED,
        eligible_holding_ids=(uid(500),),
        excluded_holding_ids=(uid(501),),
        listing_preferences=(d.PlanningListingPreference(uid(500), uid(200)),),
        holding_constraints=(
            d.PlanningHoldingConstraint(
                uid(500), Decimal("1.25"), Decimal("0.125"), Decimal("0.6")
            ),
        ),
        allocation_constraints=(
            d.PlanningConstraint(
                "input.min",
                t.TargetConstraintKind.MINIMUM_GROUP_FUNDING,
                value.node_identities[-1].id,
                amount=Decimal("2.50"),
                currency=EUR,
            ),
        ),
        cash_reserve=Decimal("1.75"),
        monetary_quantum=Decimal("0.001"),
    )
    value = replace(value, valuation=valuation, options=options)
    builder, sink, context = fixture(value)
    capture_plan_input(
        builder, context, value, request_id=UUID(int=5), input_digest=planning_input_digest(value)
    )
    builder.complete_proof_tables()
    position = rows(sink, r.ReportTableKey.PLAN_VALUATION_POSITIONS)
    assert position[0]["value"].value == Decimal("62.50")
    assert position[0]["value"].currency == CurrencyCode("USD")
    assert position[1]["value"].state is r.CellState.UNAVAILABLE
    assert position[1]["value"].quality is QualityState.PARTIAL
    cash = rows(sink, r.ReportTableKey.PLAN_VALUATION_CASH)[0]
    assert (cash["value"].value, cash["value"].currency, cash["value"].quality) == (
        Decimal("3.125"),
        CurrencyCode("USD"),
        QualityState.STALE,
    )
    assert [row["rate"].value for row in rows(sink, r.ReportTableKey.PLAN_FX)] == [
        Decimal("0.8")
    ] * 2
    assert all(row["source_id"].value == source.id for row in rows(sink, r.ReportTableKey.PLAN_FX))
    retained_options = rows(sink, r.ReportTableKey.PLAN_OPTIONS)[0]
    assert retained_options["eligibility_explicit"].value is True
    assert retained_options["cash_reserve"].value == options.cash_reserve
    assert retained_options["monetary_quantum"].value == options.monetary_quantum
    assert {
        row["relation_kind"].value for row in rows(sink, r.ReportTableKey.PLAN_INPUT_MEMBERS)
    } == {"eligible", "excluded", "restricted_group", "missing_input"}
    assert rows(sink, r.ReportTableKey.PLAN_HOLDING_CONSTRAINTS)[0][
        "value_increment"
    ].value == Decimal("0.125")
    assert (
        rows(sink, r.ReportTableKey.PLAN_ALLOCATION_CONSTRAINTS)[0]["node_id"].value
        == value.node_identities[-1].id
    )
    assert rows(sink, r.ReportTableKey.PLAN_LISTING_PREFERENCES)[0]["listing_id"].value == uid(200)
    assert len(rows(sink, r.ReportTableKey.PLAN_NODE_IDENTITIES)) == len(value.node_identities)
    assert len(rows(sink, r.ReportTableKey.PLAN_CATALOG_LISTINGS)) == len(value.catalog.listings)
    assert len(rows(sink, r.ReportTableKey.PLAN_CATALOG_INSTRUMENTS)) == len(
        value.catalog.instruments
    )
    assert any(
        row["version"].value == "broker-fixing-v7"
        for row in rows(sink, r.ReportTableKey.PLAN_SOURCE_DETAILS)
    )
    assert rows(sink, r.ReportTableKey.PLAN_INPUT_HEADER)[0][
        "input_digest"
    ].value == planning_input_digest(value)


@pytest.mark.parametrize("eligible", [None, ()])
def test_default_and_explicit_empty_eligibility_remain_distinct(
    eligible: tuple[str, ...] | None,
) -> None:
    value = planning_input()
    value = replace(value, options=replace(value.options, eligible_holding_ids=eligible))
    builder, sink, context = fixture(value)
    capture_plan_input(
        builder, context, value, request_id=UUID(int=5), input_digest=planning_input_digest(value)
    )
    builder.complete_proof_tables()
    assert rows(sink, r.ReportTableKey.PLAN_OPTIONS)[0]["eligibility_explicit"].value is (
        eligible is not None
    )
    assert not rows(sink, r.ReportTableKey.PLAN_INPUT_MEMBERS)


def test_mismatched_saved_input_digest_rejects_before_any_operand_copy() -> None:
    value = planning_input()
    builder, sink, context = fixture(value)
    with pytest.raises(ReportServiceError):
        capture_plan_input(builder, context, value, request_id=UUID(int=5), input_digest="0" * 64)
    assert not builder.proof_table_keys and not sink.chunks


def test_full_plan_result_uses_distinct_writers_for_target_and_effective_constraints() -> None:
    value = planning_input()
    result = calculate_contribution_plan(value)
    builder, sink, context = fixture(value)
    builder.add_table(
        r.ReportTableKey.TARGET_CONSTRAINTS,
        (
            _constraint_row(builder, context, UUID(value.target_version_id), constraint)
            for constraint in value.target_content.constraints
        ),
    )
    request = ContributionPlanRequestModel(
        id=UUID(int=5),
        target_version_id=UUID(value.target_version_id),
        input_digest=planning_input_digest(value),
        source_cutoff_at=AT,
    )
    revision = ContributionPlanResultModel(
        id=UUID(int=6),
        content_digest=contribution_plan_result_digest(result),
        method_version=value.method_version,
        created_at=AT,
    )
    _capture_plan(builder, result, revision, request, value)
    builder.complete_proof_tables()
    assert len(rows(sink, r.ReportTableKey.PLAN_EFFECTIVE_CONSTRAINTS)) == len(
        result.summary.constraints
    )
    assert len(rows(sink, r.ReportTableKey.TARGET_CONSTRAINTS)) == len(
        value.target_content.constraints
    )
    assert rows(sink, r.ReportTableKey.DRIFT_TOTALS)
    assert rows(sink, r.ReportTableKey.PLAN_INPUT_HEADER)
