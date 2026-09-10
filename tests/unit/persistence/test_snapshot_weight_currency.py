"""Position values cannot form reporting weights without sourced currency conversion."""

from decimal import Decimal

import pytest
from trading212_application.views import QualityView, ViewQuality
from trading212_persistence.models import (
    InstrumentModel,
    ListingModel,
    PortfolioSnapshotModel,
    SnapshotPositionModel,
)
from trading212_persistence.portfolio_service import _position_view, _snapshot_weight

from tests.unit.domain.report_factories import AT, uid

pytestmark = pytest.mark.unit


def test_position_preserves_native_value_but_refuses_an_unsourced_fx_weight() -> None:
    snapshot = PortfolioSnapshotModel(
        reporting_currency="EUR", portfolio_total=Decimal("100"), calculation_version="1.0.0"
    )
    item = SnapshotPositionModel(
        quantity=Decimal("1"),
        current_price=Decimal("25"),
        market_value=Decimal("25"),
        cost_basis=None,
        unrealized_pnl=None,
        currency="USD",
        value_origin="observed_provider",
        provenance={},
    )
    listing = ListingModel(id=uid(1), ticker="SYNTH", trading_currency="USD")
    instrument = InstrumentModel(canonical_name="Synthetic company", instrument_type="equity")
    quality = QualityView(
        state=ViewQuality.PARTIAL, as_of=AT, source_timestamp=AT, freshness_threshold_seconds=3600
    )
    view = _position_view(item, listing, instrument, snapshot, quality)
    assert view.market_value.value == Decimal("25")
    assert view.market_value.currency == "USD"
    assert view.direct_weight is None
    item.currency = "EUR"
    assert _position_view(item, listing, instrument, snapshot, quality).direct_weight == Decimal(
        "0.25"
    )


def test_zero_native_cash_is_zero_weight_only_with_a_valid_reporting_denominator() -> None:
    snapshot = PortfolioSnapshotModel(reporting_currency="EUR", portfolio_total=Decimal("100"))
    assert _snapshot_weight(Decimal("0"), "EUR", snapshot) == Decimal("0")
    assert _snapshot_weight(Decimal("0"), "USD", snapshot) is None
    snapshot.portfolio_total = Decimal("0")
    assert _snapshot_weight(Decimal("0"), "EUR", snapshot) is None
