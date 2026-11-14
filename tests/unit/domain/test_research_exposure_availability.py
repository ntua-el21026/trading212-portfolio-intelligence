"""Research distinguishes wholly unknown exposure from sourced zero and subtotals."""

from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest
from trading212_analytics.xray import calculate_xray, convert_xray_money
from trading212_domain import xray as d
from trading212_domain.enums import QualityState, ValueOrigin
from trading212_domain.research import ResearchExposureReason
from trading212_domain.research_facts import (
    ResearchPortfolioFacts,
    ResearchXrayPin,
    copy_research_portfolio_facts,
)
from trading212_domain.research_serialization import (
    research_portfolio_facts_from_json,
    research_record_bytes,
)
from trading212_domain.values import CurrencyCode
from trading212_domain.xray_codec import encode_xray_result
from trading212_domain.xray_result import XrayCalculation

from tests.unit.analytics.xray_factories import Builder, metric, uid

pytestmark = pytest.mark.unit

GBP = CurrencyCode("GBP")
ENTITY = uid(110)


def _missing_fx(builder: Builder, *, entity: UUID = ENTITY, fund: bool = False) -> None:
    """Known EUR 125 has no allowed EUR/GBP quote; identity remains evidenced."""
    instrument = uid(20) if fund else uid(10)
    row = builder.position(instrument, "125")
    builder.positions[-1] = replace(
        row, reporting_value=convert_xray_money(row.reporting_value, GBP)
    )
    builder.licensed_fx.append(d.XrayLicensedFx(row.root.key, row.reporting_value, GBP, ()))
    builder.identity(uid(10), entity)
    if fund:
        builder.fund(uid(20), ((uid(10), "1"),))


def _known_money(builder: Builder, amount: str) -> None:
    row = builder.position(uid(11), amount)
    known = metric(amount, row.valuation_refs, currency=GBP)
    builder.positions[-1] = replace(row, original_value=known, reporting_value=known)
    builder.identity(uid(11), ENTITY)


def _copy(builder: Builder) -> tuple[XrayCalculation, ResearchPortfolioFacts]:
    builder.reporting_currency = GBP
    for entity in sorted({item.entity_id for item in builder.entities}, key=str):
        builder.classifications_for(entity, key=str(entity))
    calculation = calculate_xray(builder.finish())
    before = encode_xray_result(calculation)
    pin = ResearchXrayPin(
        owner_id=calculation.owner_id,
        account_id=calculation.account_id,
        run_id=uid(123),
        snapshot_id=calculation.snapshot_id,
        input_digest=calculation.input_digest,
        result_digest=calculation.content_digest,
        reporting_currency=calculation.reporting_currency,
        valuation_at=calculation.valuation_at.value,
        source_cutoff_at=calculation.source_cutoff_at.value,
        quality_evaluated_at=calculation.quality_evaluated_at.value,
        policy_id=calculation.policy.id,
        policy_version=calculation.policy.version,
    )
    copied = copy_research_portfolio_facts(pin, calculation, ENTITY)
    assert encode_xray_result(calculation) == before
    assert research_portfolio_facts_from_json(research_record_bytes(copied)) == copied
    return calculation, copied


@pytest.mark.parametrize("fund", [False, True], ids=["direct", "fund"])
def test_all_unvalued_held_entity_is_unavailable_in_research(fund: bool) -> None:
    builder = Builder()
    _missing_fx(builder, fund=fund)
    calculation, copied = _copy(builder)
    paths = tuple(path for path in calculation.terminal_paths if path.entity_id == ENTITY)
    assert paths and all(path.relative_coefficient > 0 for path in paths)
    assert all(
        path.money_coefficient is None and path.reporting_value.value is None for path in paths
    )
    assert calculation.portfolio_summary.total.value is None
    bucket = next(
        item
        for item in calculation.exposure_buckets
        if item.dimension is d.XrayDimension.COMPANY and item.bucket_key == str(ENTITY)
    )
    # X-ray deliberately retains a known-subtotal lower bound. It does not prove
    # that the held company's reporting-currency exposure is actually zero.
    assert bucket.effective.value is not None and bucket.effective.value.amount == Decimal("0")
    assert bucket.effective.bound is d.XrayBound.LOWER_BOUND
    assert copied.effective_exposure is None
    assert copied.availability is d.XrayAvailability.UNAVAILABLE
    assert copied.reason is ResearchExposureReason.CAPTURED_VALUE_UNAVAILABLE
    assert copied.upstream_reason is d.XrayReason.INCOMPLETE_VALUATION
    assert copied.origin is ValueOrigin.UNAVAILABLE and copied.quality is QualityState.PARTIAL
    assert copied.bound is d.XrayBound.LOWER_BOUND
    assert copied.path_keys == bucket.path_keys == tuple(path.key for path in paths)
    assert copied.source_reference_ids == bucket.source_reference_ids
    assert copied.metric_source_reference_ids == bucket.effective.source_reference_ids
    assert copied.confidence == bucket.effective.confidence
    assert tuple(
        (item.code, item.reason, item.source_reference_ids, item.path_keys)
        for item in copied.warnings
    ) == tuple(
        (item.code, item.reason, item.source_reference_ids, item.path_keys)
        for item in calculation.warnings
    )


def test_exact_sourced_zero_remains_available_in_research() -> None:
    builder = Builder()
    _known_money(builder, "0")
    calculation, copied = _copy(builder)
    assert calculation.portfolio_summary.total.value is not None
    assert copied.effective_exposure is not None
    assert copied.effective_exposure.amount == Decimal("0")
    assert copied.availability is d.XrayAvailability.AVAILABLE
    assert copied.reason is None and copied.upstream_reason is None
    assert copied.bound is d.XrayBound.EXACT and copied.quality is QualityState.FRESH
    assert all(path.money_coefficient == 0 for path in calculation.terminal_paths)


def test_positive_known_entity_contribution_rounded_to_zero_remains_available() -> None:
    builder = Builder()
    row = builder.position(uid(20), "0.000000000000000001")
    known = metric("0.000000000000000001", row.valuation_refs, currency=GBP)
    builder.positions[-1] = replace(row, original_value=known, reporting_value=known)
    builder.identity(uid(10), ENTITY)
    builder.fund(uid(20), ((uid(10), "0.1"), (None, "0.9")))
    calculation, copied = _copy(builder)
    path = next(path for path in calculation.terminal_paths if path.entity_id == ENTITY)
    assert path.money_coefficient is not None and path.money_coefficient > 0
    assert path.reporting_value.value is not None and path.reporting_value.value.amount == 0
    assert copied.effective_exposure is not None and copied.effective_exposure.amount == 0
    assert copied.availability is d.XrayAvailability.AVAILABLE and copied.reason is None
    assert copied.bound is d.XrayBound.EXACT and copied.quality is QualityState.FRESH


@pytest.mark.parametrize("known", ["0", "30"], ids=["known-zero", "known-positive"])
def test_partial_known_entity_contribution_remains_an_explicit_lower_bound(known: str) -> None:
    builder = Builder()
    _missing_fx(builder)
    _known_money(builder, known)
    calculation, copied = _copy(builder)
    paths = tuple(path for path in calculation.terminal_paths if path.entity_id == ENTITY)
    assert len(paths) == 2 and sum(path.money_coefficient is None for path in paths) == 1
    assert calculation.portfolio_summary.total.value is None
    assert copied.effective_exposure is not None and copied.effective_exposure.amount == Decimal(
        known
    )
    assert copied.availability is d.XrayAvailability.AVAILABLE and copied.reason is None
    assert copied.bound is d.XrayBound.LOWER_BOUND and copied.quality is QualityState.PARTIAL
    assert set(copied.path_keys) == {path.key for path in paths}


def test_unrelated_missing_fx_does_not_hide_a_valued_entity() -> None:
    builder = Builder()
    _missing_fx(builder, entity=uid(111))
    _known_money(builder, "30")
    calculation, copied = _copy(builder)
    assert calculation.portfolio_summary.total.value is None
    assert copied.effective_exposure is not None and copied.effective_exposure.amount == Decimal(
        "30"
    )
    assert copied.availability is d.XrayAvailability.AVAILABLE and copied.reason is None
    assert copied.bound is d.XrayBound.LOWER_BOUND and copied.quality is QualityState.PARTIAL
    assert copied.path_keys == tuple(
        path.key for path in calculation.terminal_paths if path.entity_id == ENTITY
    )
