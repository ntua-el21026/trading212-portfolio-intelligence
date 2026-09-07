"""Versioned synthetic source identities and exact source-controlled observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from importlib.resources import files

from trading212_domain.enums import QualityState
from trading212_domain.errors import DomainError
from trading212_domain.fixtures import fixture_uuid
from trading212_domain.source_details import (
    ClassificationDimension,
    ConstituentState,
    CorporateActionKind,
    CorporateActionObservation,
    SourceIdentifier,
    SourceIdentifierKind,
)
from trading212_domain.sources import (
    BenchmarkObservation,
    FxObservation,
    LicensePermission,
    MarketSession,
    ObservationState,
    PriceBasis,
    PriceObservation,
    SourceCalendar,
    SourceCoverage,
    SourceGap,
    SourceLicense,
    SourcePeriod,
    SourceReason,
    SourceSeries,
    SourceSeriesKind,
    source_id,
    source_key,
)
from trading212_domain.values import CurrencyCode, exact_decimal

from .bounded_json import DecodeFailure, JsonValue, decode_replay_json

PROVIDER_ID = str(fixture_uuid("reference-replay/provider/v1"))
LICENSE_ID = str(fixture_uuid("reference-replay/license/v1"))
MAPPING_ID = str(fixture_uuid("reference-replay/mapping/v1"))
FUND_SERIES_ID = str(fixture_uuid("reference-replay/fund/v1"))
FIXTURE_KNOWN_AT = datetime(2026, 8, 31, 12, tzinfo=UTC)
FIXTURE_PERIOD = SourcePeriod(start=date(2026, 8, 3), end=date(2026, 8, 28))
ADAPTER_VERSION = "reference-replay-1"
PROVIDER_KEY = "reference-replay"
CALENDAR_ID = "synthetic-weekdays"
CALENDAR_VERSION = "2026-08-v1"


def synthetic_license() -> SourceLicense:
    return SourceLicense(
        id=LICENSE_ID,
        provider_id=PROVIDER_ID,
        version="synthetic-license-1",
        effective_at=datetime(2026, 1, 1, tzinfo=UTC),
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=LicensePermission.ALLOWED,
        export=LicensePermission.ALLOWED,
        retention_days=3650,
        attribution="Synthetic reference data; no market-data provider.",
        evidence_key="synthetic-license-v1",
    )


def synthetic_series(
    *, owner_id: str, instrument_id: str, listing_id: str
) -> tuple[SourceSeries, ...]:
    return tuple(
        SourceSeries(
            id=str(fixture_uuid(f"reference-replay/series/{kind}/{basis}")),
            owner_id=owner_id,
            provider_id=PROVIDER_ID,
            license_version_id=LICENSE_ID,
            kind=kind,
            provider_key="SYNTHETIC_EQ_1"
            if kind is SourceSeriesKind.SECURITY_PRICE
            else "SYNTHETIC_INDEX_1",
            mapping_version="synthetic-mapping-1",
            basis=basis,
            currency=CurrencyCode("EUR"),
            calendar_id=CALENDAR_ID,
            calendar_version=CALENDAR_VERSION,
            mapping_id=MAPPING_ID if kind is SourceSeriesKind.SECURITY_PRICE else None,
            instrument_id=instrument_id if kind is SourceSeriesKind.SECURITY_PRICE else None,
            listing_id=listing_id if kind is SourceSeriesKind.SECURITY_PRICE else None,
        )
        for kind in SourceSeriesKind
        for basis in PriceBasis
    )


def fixture_object(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError("invalid replay object")
    return value


def fixture_rows(value: JsonValue) -> list[dict[str, JsonValue]]:
    if not isinstance(value, list) or len(value) > 1000:
        raise ValueError("invalid replay record list")
    return [fixture_object(row) for row in value]


def fixture_text(value: JsonValue) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid replay text")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class SyntheticFundMapping:
    """Trusted owner-scoped binding for the fixed synthetic fund fixture."""

    owner_id: str
    fund_series_id: str
    constituent_instrument_id: str

    def __post_init__(self) -> None:
        for field in ("owner_id", "fund_series_id", "constituent_instrument_id"):
            source_id(getattr(self, field), field)
        if self.fund_series_id != FUND_SERIES_ID:
            raise ValueError("unknown synthetic fund mapping")


@dataclass(frozen=True, slots=True, kw_only=True)
class SyntheticConstituent:
    source_key: str
    weight: Decimal
    state: ConstituentState


def _constituents(document: dict[str, JsonValue]) -> tuple[SyntheticConstituent, ...]:
    result = []
    for row in fixture_rows(document["constituents"]):
        key = source_key(fixture_text(row["key"]))
        weight = exact_decimal(fixture_text(row["weight"]))
        state = fixture_text(row["state"])
        if not 0 <= weight <= 1:
            raise ValueError("invalid synthetic constituent weight")
        result.append(
            SyntheticConstituent(
                source_key=key,
                weight=weight,
                state=ConstituentState.RESOLVED if state == "known" else ConstituentState(state),
            )
        )
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
        if sum((row.weight for row in result), Decimal(0)) > 1:
            raise ValueError("invalid synthetic constituent total")
    if len({row.source_key for row in result}) != len(result):
        raise ValueError("duplicate synthetic constituent")
    return tuple(result)


@dataclass(frozen=True, slots=True, kw_only=True)
class SyntheticData:
    calendar: SourceCalendar
    prices: tuple[tuple[PriceBasis, tuple[PriceObservation, ...]], ...]
    fx: tuple[FxObservation, ...]
    benchmark: tuple[tuple[PriceBasis, tuple[BenchmarkObservation, ...]], ...]
    actions: tuple[CorporateActionObservation, ...]
    identifiers: tuple[SourceIdentifier, ...]
    classifications: tuple[tuple[ClassificationDimension, str], ...]
    constituents: tuple[SyntheticConstituent, ...]


def decode_synthetic_data(payload: bytes | None = None) -> SyntheticData | DecodeFailure:
    """Minimize known fields before returning any reusable canonical record."""
    if payload is None:
        payload = (
            files("trading212_reference_data").joinpath("fixtures/synthetic-v1.json").read_bytes()
        )
    document = decode_replay_json(payload)
    if isinstance(document, DecodeFailure):
        return document
    result: SyntheticData | None = None
    try:
        if document.get("schema") != "reference-replay/v1":
            raise ValueError("invalid replay schema version")
        if (
            document.get("revision") != "synthetic-1"
            or type(document.get("revision_order")) is not int
            or document.get("revision_order") != 1
        ):
            raise ValueError("invalid replay revision")
        if (
            document.get("calendar_id") != CALENDAR_ID
            or document.get("calendar_version") != CALENDAR_VERSION
        ):
            raise ValueError("invalid replay calendar")
        period = fixture_object(document["period"])
        if (period.get("start"), period.get("end")) != (
            FIXTURE_PERIOD.start.isoformat(),
            FIXTURE_PERIOD.end.isoformat(),
        ):
            raise ValueError("invalid replay period")
        calendar = SourceCalendar(
            id=CALENDAR_ID,
            version=CALENDAR_VERSION,
            timezone="UTC",
            period=FIXTURE_PERIOD,
            sessions=tuple(
                MarketSession(
                    session_date=date.fromisoformat(fixture_text(row["date"])),
                    close_at=datetime.fromisoformat(fixture_text(row["close_at"])),
                )
                for row in fixture_rows(document["sessions"])
            ),
        )
        prices = fixture_object(document["prices"])
        instrument = fixture_object(document["instrument"])
        result = SyntheticData(
            calendar=calendar,
            prices=tuple(
                (
                    basis,
                    tuple(
                        PriceObservation(
                            session_date=date.fromisoformat(fixture_text(row["date"])),
                            effective_at=datetime.fromisoformat(fixture_text(row["effective_at"])),
                            value=exact_decimal(fixture_text(row["value"]))
                            if row["value"] is not None
                            else None,
                            state=ObservationState(fixture_text(row["state"])),
                            corporate_action_revision=fixture_text(row["corporate_action_revision"])
                            if row.get("corporate_action_revision") is not None
                            else None,
                        )
                        for row in fixture_rows(prices[basis.value])
                    ),
                )
                for basis in PriceBasis
            ),
            fx=tuple(
                FxObservation(
                    base=CurrencyCode(fixture_text(row["base"])),
                    quote=CurrencyCode(fixture_text(row["quote"])),
                    session_date=date.fromisoformat(fixture_text(row["date"])),
                    effective_at=datetime.fromisoformat(fixture_text(row["effective_at"])),
                    rate=exact_decimal(fixture_text(row["rate"]))
                    if row["rate"] is not None
                    else None,
                    batch_key=fixture_text(row["batch_key"]),
                    state=ObservationState(fixture_text(row["state"])),
                )
                for row in fixture_rows(document["fx"])
            ),
            benchmark=tuple(
                (
                    basis,
                    tuple(
                        BenchmarkObservation(
                            session_date=date.fromisoformat(fixture_text(row["date"])),
                            effective_at=datetime.fromisoformat(fixture_text(row["effective_at"])),
                            level=exact_decimal(fixture_text(row["level"]))
                            if row["level"] is not None
                            else None,
                            state=ObservationState(fixture_text(row["state"])),
                        )
                        for row in fixture_rows(fixture_object(document["benchmark"])[basis.value])
                    ),
                )
                for basis in PriceBasis
            ),
            actions=tuple(
                CorporateActionObservation(
                    source_key=fixture_text(row["key"]),
                    session_date=date.fromisoformat(fixture_text(row["effective_date"])),
                    effective_at=datetime.fromisoformat(
                        fixture_text(row["effective_date"]) + "T16:00:00Z"
                    ),
                    kind=CorporateActionKind(fixture_text(row["kind"])),
                    state=ObservationState(fixture_text(row.get("state", "available"))),
                    ratio=exact_decimal(fixture_text(row["ratio"]))
                    if row["ratio"] is not None
                    else None,
                    amount=exact_decimal(fixture_text(row["amount"]))
                    if row["amount"] is not None
                    else None,
                    currency=CurrencyCode(fixture_text(row["currency"]))
                    if row["currency"] is not None
                    else None,
                    target_instrument_id=fixture_text(row["target_instrument_id"])
                    if row.get("target_instrument_id") is not None
                    else None,
                    correction_source_key=fixture_text(row["correction_source_key"])
                    if row.get("correction_source_key") is not None
                    else None,
                    source_revision=fixture_text(row["revision"]),
                )
                for row in fixture_rows(document["actions"])
            ),
            identifiers=(
                SourceIdentifier(
                    kind=SourceIdentifierKind.ISIN, value=fixture_text(instrument["isin"])
                ),
                SourceIdentifier(
                    kind=SourceIdentifierKind.PROVIDER_KEY,
                    value=fixture_text(instrument["provider_key"]),
                ),
                SourceIdentifier(
                    kind=SourceIdentifierKind.MIC_TICKER,
                    value=fixture_text(instrument["ticker"]),
                    mic=fixture_text(instrument["mic"]),
                ),
            ),
            classifications=tuple(
                (
                    ClassificationDimension(fixture_text(row["dimension"])),
                    source_key(fixture_text(row["category"])),
                )
                for row in fixture_rows(document["classifications"])
            ),
            constituents=_constituents(document),
        )
        _validate_data(result)
    except (DomainError, ValueError, KeyError, TypeError):
        result = None
    # Return a value outside the exception handler; never retain the raw parser cause.
    return result if result is not None else DecodeFailure.INVALID_SCHEMA


def _validate_data(data: SyntheticData) -> None:
    sessions = {session.session_date: session.close_at for session in data.calendar.sessions}
    groups = [rows for _, rows in data.prices] + [rows for _, rows in data.benchmark]
    for rows in groups:
        if len({row.session_date for row in rows}) != len(rows) or any(
            sessions.get(row.session_date) != row.effective_at for row in rows
        ):
            raise ValueError("invalid replay session observations")
    if len({(r.base, r.quote, r.session_date) for r in data.fx}) != len(data.fx) or any(
        sessions.get(row.session_date) != row.effective_at for row in data.fx
    ):
        raise ValueError("invalid replay FX observations")
    if len({row.source_key for row in data.actions}) != len(data.actions) or any(
        not FIXTURE_PERIOD.start <= row.session_date <= FIXTURE_PERIOD.end for row in data.actions
    ):
        raise ValueError("invalid replay actions")
    revisions = {row.source_revision for row in data.actions}
    if len(revisions) != len(data.actions) or any(
        row.corporate_action_revision is not None and row.corporate_action_revision not in revisions
        for _, rows in data.prices
        for row in rows
    ):
        raise ValueError("invalid replay action revision relationship")
    if (
        SourceIdentifier(kind=SourceIdentifierKind.PROVIDER_KEY, value="SYNTHETIC_EQ_1")
        not in data.identifiers
    ):
        raise ValueError("incompatible replay instrument key")
    if len({dimension for dimension, _ in data.classifications}) != len(data.classifications):
        raise ValueError("duplicate replay classification")


def replay_coverage(
    *,
    expected_dates: tuple[date, ...],
    available_dates: tuple[date, ...],
) -> SourceCoverage:
    available = set(available_dates)
    gaps = tuple(
        SourceGap(session_date=day, reason=SourceReason.MISSING_SESSION)
        for day in expected_dates
        if day not in available
    )
    return SourceCoverage(
        expected_count=len(expected_dates),
        available_count=len(available.intersection(expected_dates)),
        gaps=gaps,
        quality=QualityState.FRESH if not gaps else QualityState.PARTIAL,
        reason=SourceReason.MISSING_SESSION if gaps else None,
    )
