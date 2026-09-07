"""Declared synthetic histories with independent cash/quantity conservation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Literal

from trading212_domain import build_synthetic_identity
from trading212_domain.entities import BrokerAccount, Instrument, Listing
from trading212_domain.enums import BrokerEnvironment, Provider, RecordStatus
from trading212_domain.fixtures import fixture_uuid
from trading212_domain.identifiers import BrokerAccountId, InstrumentId, ListingId
from trading212_domain.values import CurrencyCode, Instant

HistoryVariant = Literal["annual", "point_in_time"]
HISTORY_RECEIPT = datetime(2026, 8, 31, 12, tzinfo=UTC)
HISTORY_CONTEXT = Context(prec=80, rounding=ROUND_HALF_EVEN)


def history_id(key: str) -> str:
    return str(fixture_uuid(f"historical-intelligence-v1/{key}"))


def close_at(day: date) -> datetime:
    return datetime.combine(day, time(16), tzinfo=UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class SyntheticHistoryInstrument:
    instrument: Instrument
    listing: Listing


@dataclass(frozen=True, slots=True, kw_only=True)
class SyntheticHistoryActivity:
    key: str
    kind: Literal["deposit", "withdrawal", "buy", "sell", "dividend", "fee", "tax", "interest"]
    at: datetime
    currency: str
    amount: Decimal
    quantity: Decimal = Decimal(0)
    gross: Decimal | None = None
    withholding: Decimal | None = None
    order_id: int | None = None
    fill_id: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SyntheticHistoryState:
    quantities: tuple[tuple[str, Decimal], ...]
    cash: tuple[tuple[str, Decimal], ...]
    acquisition_costs: tuple[tuple[str, Decimal], ...]
    realized_profit: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class SyntheticHistoryScenario:
    variant: HistoryVariant
    account: BrokerAccount
    instruments: tuple[SyntheticHistoryInstrument, ...]
    start: date
    end: date
    activities: tuple[SyntheticHistoryActivity, ...]

    @property
    def opening_at(self) -> datetime:
        return close_at(self.start)

    @property
    def sessions(self) -> tuple[date, ...]:
        return tuple(
            self.start + timedelta(days=day) for day in range((self.end - self.start).days + 1)
        )

    def price(self, currency: str, day: date) -> Decimal:
        elapsed = Decimal((day - self.start).days)
        with localcontext(HISTORY_CONTEXT):
            if currency == "EUR":
                return Decimal("100") + elapsed * Decimal("0.04")
            if currency == "USD":
                return Decimal("40") + elapsed * Decimal("0.015")
        raise ValueError("Unknown synthetic historical price currency")

    def fx(self, day: date) -> Decimal:
        """Explicit synthetic USD/EUR fixing; not inferred from wallet impacts."""
        with localcontext(HISTORY_CONTEXT):
            return Decimal("0.9") + Decimal((day - self.start).days % 20) * Decimal("0.001")

    def benchmark(self, currency: str, day: date) -> Decimal:
        elapsed = (day - self.start).days
        with localcontext(HISTORY_CONTEXT):
            if currency == "EUR":
                return (
                    Decimal("1000")
                    + Decimal(elapsed) * Decimal("0.35")
                    + Decimal(elapsed % 7) * Decimal("0.1")
                )
            if currency == "USD":
                return (
                    Decimal("500")
                    + Decimal(elapsed) * Decimal("0.2")
                    - Decimal(elapsed % 5) * Decimal("0.05")
                )
        raise ValueError("Unknown synthetic historical benchmark currency")

    def state(self, at: datetime, *, include_equal: bool = True) -> SyntheticHistoryState:
        """Independent fixture bookkeeping, never a product performance calculator."""
        quantities = {"EUR": Decimal("10"), "USD": Decimal("5")}
        cash = {"EUR": Decimal("500"), "USD": Decimal("0")}
        costs = {"EUR": Decimal("1000"), "USD": Decimal("200")}
        realized = {"EUR": Decimal("0"), "USD": Decimal("0")}
        with localcontext(HISTORY_CONTEXT):
            for event in self.activities:
                if event.at > at or (event.at == at and not include_equal):
                    continue
                cash[event.currency] += event.amount
                if event.kind == "buy":
                    quantities[event.currency] += event.quantity
                    costs[event.currency] -= event.amount
                elif event.kind == "sell":
                    removed_cost = (
                        costs[event.currency] / quantities[event.currency] * event.quantity
                    )
                    costs[event.currency] -= removed_cost
                    realized[event.currency] += event.amount - removed_cost
                    quantities[event.currency] -= event.quantity
            costs = {
                currency: value.quantize(Decimal("0.000000000000000001"))
                for currency, value in costs.items()
            }
            realized = {
                currency: value.quantize(Decimal("0.000000000000000001"))
                for currency, value in realized.items()
            }
        return SyntheticHistoryState(
            quantities=tuple(sorted(quantities.items())),
            cash=tuple(sorted(cash.items())),
            acquisition_costs=tuple(sorted(costs.items())),
            realized_profit=tuple(sorted(realized.items())),
        )


def build_history_scenario(variant: HistoryVariant) -> SyntheticHistoryScenario:
    if variant not in ("annual", "point_in_time"):
        raise ValueError("Unknown synthetic historical scenario")
    identity = build_synthetic_identity()
    start = date(2023, 12, 31) if variant == "annual" else date(2026, 8, 1)
    end = date(2025, 12, 31) if variant == "annual" else date(2026, 8, 22)
    created = Instant(close_at(start))
    account = BrokerAccount(
        id=BrokerAccountId(fixture_uuid(f"historical-intelligence-v1/{variant}/account")),
        connection_id=identity.connection.id,
        provider_account_id=f"synthetic-history-{variant}",
        account_type="invest",
        base_currency=CurrencyCode("EUR"),
        display_name="Synthetic Historical Portfolio"
        if variant == "annual"
        else "Synthetic Point-in-time Portfolio",
        status=RecordStatus.ACTIVE,
        first_seen_at=created,
        last_seen_at=Instant(HISTORY_RECEIPT),
    )
    instruments = []
    provider_prefix = "ANNUAL" if variant == "annual" else "TIMELY"
    for index, currency in enumerate(("EUR", "USD"), start=1):
        key = f"{variant}/{currency}"
        instrument = Instrument(
            InstrumentId(fixture_uuid(f"historical-intelligence-v1/{key}/instrument")),
            f"Synthetic Historical {currency} Equity"
            if variant == "annual"
            else f"Synthetic Timely {currency} Equity",
            "equity",
            f"XS00000000{1 if variant == 'annual' else 2}{index}",
        )
        listing = Listing(
            id=ListingId(fixture_uuid(f"historical-intelligence-v1/{key}/listing")),
            instrument_id=instrument.id,
            provider=Provider.SYNTHETIC,
            environment=BrokerEnvironment.SYNTHETIC,
            provider_instrument_id=f"HIST_{provider_prefix}_{currency}",
            ticker=f"HIST_{provider_prefix}_{currency}",
            trading_currency=CurrencyCode(currency),
            status=RecordStatus.ACTIVE,
            valid_from=created,
            exchange_mic="XOFF",
        )
        instruments.append(SyntheticHistoryInstrument(instrument=instrument, listing=listing))
    scenario = SyntheticHistoryScenario(
        variant=variant,
        account=account,
        instruments=tuple(instruments),
        start=start,
        end=end,
        activities=(),
    )
    if variant == "point_in_time":
        # This separate scenario isolates use-time knowledge and twenty paired
        # benchmark returns. The annual scenario supplies the flow/trade/income
        # history; zero activity here is a declared complete source observation.
        return scenario
    dates = (
        (
            date(2025, 1, 15),
            date(2025, 1, 16),
            date(2025, 2, 3),
            date(2025, 2, 10),
            date(2025, 6, 15),
        )
        if variant == "annual"
        else tuple(start + timedelta(days=day) for day in (3, 4, 7, 9, 15))
    )
    deposit_day, buy_day, sell_day, withdrawal_day, income_day = dates
    with localcontext(HISTORY_CONTEXT):
        purchase_amount = -scenario.price("EUR", buy_day) * Decimal("2")
    activities = [
        SyntheticHistoryActivity(
            key="deposit",
            kind="deposit",
            at=close_at(deposit_day),
            currency="EUR",
            amount=Decimal("200"),
        ),
        SyntheticHistoryActivity(
            key="purchase",
            kind="buy",
            at=close_at(buy_day),
            currency="EUR",
            amount=purchase_amount,
            quantity=Decimal("2"),
            order_id=71001,
            fill_id=81001,
        ),
        SyntheticHistoryActivity(
            key="fee",
            kind="fee",
            at=close_at(buy_day) + timedelta(seconds=1),
            currency="EUR",
            amount=Decimal("-1"),
        ),
        SyntheticHistoryActivity(
            key="sale",
            kind="sell",
            at=close_at(sell_day),
            currency="EUR",
            amount=scenario.price("EUR", sell_day),
            quantity=Decimal("1"),
            order_id=71002,
            fill_id=81002,
        ),
        SyntheticHistoryActivity(
            key="withdrawal",
            kind="withdrawal",
            at=close_at(withdrawal_day),
            currency="EUR",
            amount=Decimal("-100"),
        ),
        SyntheticHistoryActivity(
            key="eur-income",
            kind="dividend",
            at=datetime.combine(income_day, time(0), tzinfo=UTC),
            currency="EUR",
            amount=Decimal("30"),
            quantity=Decimal("10"),
            gross=Decimal("36"),
            withholding=Decimal("6"),
        ),
        SyntheticHistoryActivity(
            key="usd-income",
            kind="dividend",
            at=datetime.combine(income_day, time(0), tzinfo=UTC),
            currency="USD",
            amount=Decimal("5"),
            quantity=Decimal("5"),
            gross=Decimal("6"),
            withholding=Decimal("1"),
        ),
        SyntheticHistoryActivity(
            key="income-adjustment",
            kind="dividend",
            at=datetime.combine(income_day + timedelta(days=1), time(0), tzinfo=UTC),
            currency="EUR",
            amount=Decimal("-2"),
            quantity=Decimal("10"),
            gross=Decimal("-2"),
            withholding=Decimal("0"),
        ),
        SyntheticHistoryActivity(
            key="interest",
            kind="interest",
            at=close_at(income_day + timedelta(days=2)),
            currency="EUR",
            amount=Decimal("0.5"),
        ),
    ]
    if variant == "annual":
        activities.extend(
            (
                SyntheticHistoryActivity(
                    key="prior-eur-income",
                    kind="dividend",
                    at=datetime(2024, 6, 15, tzinfo=UTC),
                    currency="EUR",
                    amount=Decimal("20"),
                    quantity=Decimal("10"),
                    gross=Decimal("24"),
                    withholding=Decimal("4"),
                ),
            )
        )
    return replace(
        scenario, activities=tuple(sorted(activities, key=lambda row: (row.at, row.key)))
    )
