"""Report numeric quality includes the pinned snapshot and weight denominator."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session
from trading212_domain import reports as r
from trading212_domain.enums import QualityState
from trading212_domain.report_schema import table_schema
from trading212_domain.report_v3 import ReportSelectionV3
from trading212_domain.values import CurrencyCode
from trading212_persistence.models import (
    CalculationRunModel,
    InstrumentModel,
    ListingModel,
    PortfolioSnapshotModel,
    SnapshotCashModel,
    SnapshotPositionModel,
)
from trading212_persistence.report_builder import ReportBuilder
from trading212_persistence.report_capture_portfolio import capture_portfolio

from tests.unit.domain.report_factories import AT, selection, uid

pytestmark = pytest.mark.unit


class _Sink:
    def __init__(self) -> None:
        self.chunks: list[r.ReportChunk] = []

    def append(self, chunk: r.ReportChunk) -> None:
        self.chunks.append(chunk)

    def finish(self, summary: r.ReportCaptureSummary) -> None:
        raise AssertionError("Capture does not own the publication seal")


def _capture(
    age: timedelta,
    *,
    intrinsic: QualityState = QualityState.FRESH,
    snapshot_quality: QualityState = QualityState.FRESH,
    unavailable: bool = False,
    request: r.ReportSelection | ReportSelectionV3 | None = None,
) -> tuple[ReportBuilder, dict[str, dict[str, r.ReportCell]]]:
    snapshot = PortfolioSnapshotModel(
        id=uid(2),
        broker_account_id=uid(1),
        calculation_run_id=uid(3),
        calculation_version="1.0.0",
        valuation_at=AT,
        source_cutoff_at=AT,
        reporting_currency="EUR",
        portfolio_total=Decimal("100"),
        cash_total=Decimal("0") if unavailable else Decimal("20"),
        invested_total=None if unavailable else Decimal("80"),
        net_contributions=Decimal("75"),
        quality_state=snapshot_quality.value,
        coverage={"complete": not unavailable},
        warnings=[],
        created_at=AT,
    )
    calculation = CalculationRunModel(
        id=uid(3),
        broker_account_id=uid(1),
        calculation_name="portfolio_summary",
        version="1.0.0",
        calculated_at=AT,
        input_ids=[],
        output_fingerprint="a" * 64,
    )
    position = SnapshotPositionModel(
        id=uid(4),
        snapshot_id=snapshot.id,
        listing_id=uid(5),
        quantity=Decimal("2"),
        current_price=None if unavailable else Decimal("40"),
        market_value=None if unavailable else Decimal("80"),
        cost_basis=None if unavailable else Decimal("75"),
        unrealized_pnl=None if unavailable else Decimal("5"),
        currency="EUR",
        quality_state=intrinsic.value,
        value_origin="observed_provider",
        provenance={},
    )
    listing = ListingModel(id=uid(5), ticker="SYNTH", trading_currency="EUR")
    instrument = InstrumentModel(
        id=uid(6), canonical_name="Synthetic company", instrument_type="equity"
    )
    cash = SnapshotCashModel(
        id=uid(7),
        snapshot_id=snapshot.id,
        amount=snapshot.cash_total,
        currency="EUR",
        quality_state=intrinsic.value,
        value_origin="observed_provider",
        provenance={},
    )
    session = Mock(spec=Session, scalar=Mock(return_value=calculation))
    session.execute.return_value.yield_per.return_value = ((position, listing, instrument),)
    session.scalars.return_value.yield_per.return_value = (cash,)
    sink = _Sink()
    builder = ReportBuilder(
        replace(request or selection(), source_cutoff_at=AT + age),
        owner_id=uid(8),
        valuation_at=AT,
        sink=sink,
    )
    capture_portfolio(builder, session, snapshot)
    return builder, {
        row.key: {
            column.key: cell
            for column, cell in zip(table_schema(chunk.table).columns, row.cells, strict=True)
        }
        for chunk in sink.chunks
        for row in chunk.rows
    }


def _assert_numeric_quality(
    builder: ReportBuilder,
    rows: dict[str, dict[str, r.ReportCell]],
    expected: QualityState,
) -> None:
    context = builder.contexts["context.snapshot"]
    for key in (f"position.{uid(4)}", f"allocation.position.{uid(4)}", f"allocation.cash.{uid(7)}"):
        numeric = [cell for cell in rows[key].values() if cell.kind is r.CellKind.DECIMAL]
        assert numeric
        assert all((cell.quality or context.quality) is expected for cell in numeric)
        assert all(
            cell.quality is None if expected is context.quality else cell.quality is expected
            for cell in numeric
        )


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(seconds=900), QualityState.FRESH),
        (timedelta(seconds=900, microseconds=1), QualityState.STALE),
    ],
)
def test_snapshot_age_boundary_applies_to_all_position_and_cash_numeric_cells(
    age: timedelta, expected: QualityState
) -> None:
    builder, rows = _capture(age)
    context = builder.contexts["context.snapshot"]
    assert context.quality is expected
    _assert_numeric_quality(builder, rows, expected)
    position = rows[f"position.{uid(4)}"]
    assert {
        key: cell.value for key, cell in position.items() if cell.kind is r.CellKind.DECIMAL
    } == {
        "quantity": Decimal("2"),
        "current_price": Decimal("40"),
        "market_value": Decimal("80"),
        "provider_cost_basis": Decimal("75"),
        "provider_unrealized_profit_loss": Decimal("5"),
        "direct_weight": Decimal("0.8"),
    }
    assert (
        position["market_value"].currency
        == position["current_price"].currency
        == CurrencyCode("EUR")
    )
    assert position["market_value"].origin is r.ReportMetricOrigin.OBSERVED_PROVIDER
    assert position["direct_weight"].origin is r.ReportMetricOrigin.DERIVED_DETERMINISTIC
    assert rows[f"allocation.position.{uid(4)}"]["weight"].value == Decimal("0.8")
    assert rows[f"allocation.cash.{uid(7)}"]["weight"].value == Decimal("0.2")
    assert (context.valuation_at, context.source_cutoff_at, context.source_at) == (AT, AT, AT)
    assert (context.method_key, context.method_version) == ("portfolio_summary", "1.0.0")


@pytest.mark.parametrize(
    "intrinsic",
    [QualityState.ESTIMATED, QualityState.PARTIAL, QualityState.UNRECONCILED, QualityState.FAILED],
)
def test_stale_snapshot_never_upgrades_stronger_intrinsic_row_degradation(
    intrinsic: QualityState,
) -> None:
    builder, rows = _capture(timedelta(seconds=901), intrinsic=intrinsic)
    assert builder.contexts["context.snapshot"].quality is QualityState.STALE
    _assert_numeric_quality(builder, rows, intrinsic)


def test_fresh_rows_do_not_upgrade_a_partial_snapshot_or_its_weight_denominator() -> None:
    builder, rows = _capture(timedelta(0), snapshot_quality=QualityState.PARTIAL)
    _assert_numeric_quality(builder, rows, QualityState.PARTIAL)
    assert rows[f"position.{uid(4)}"]["direct_weight"].value == Decimal("0.8")


def test_snapshot_quality_does_not_turn_unavailable_values_into_zero_or_remove_real_zero() -> None:
    builder, rows = _capture(timedelta(seconds=901), unavailable=True)
    _assert_numeric_quality(builder, rows, QualityState.STALE)
    position = rows[f"position.{uid(4)}"]
    for key in (
        "current_price",
        "market_value",
        "provider_cost_basis",
        "provider_unrealized_profit_loss",
        "direct_weight",
    ):
        assert position[key].value is None
        assert position[key].state is r.CellState.UNAVAILABLE
        assert position[key].reason_key in builder.notes
    assert position["quantity"].value == Decimal("2")
    assert position["quantity"].state is r.CellState.AVAILABLE
    cash = rows[f"allocation.cash.{uid(7)}"]
    for key in ("value", "weight"):
        assert cash[key].value == Decimal("0")
        assert cash[key].state is r.CellState.AVAILABLE
