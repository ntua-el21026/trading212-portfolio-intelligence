"""Opt-in native custody facts for the disposable aggregation browser database."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.source_policy import assess_fx_coverage
from trading212_application.ingestion import (
    BrokerAccountDataProvider,
    IngestionCoordinator,
    RunMode,
    RunStatus,
)
from trading212_application.source_ingestion import SourceProviderRegistration
from trading212_application.source_providers import (
    FxPair,
    FxRatePage,
    FxRatesRequest,
    SourceCapability,
)
from trading212_application.sources import ProviderConfigurationState
from trading212_domain import CurrencyCode, build_synthetic_identity
from trading212_domain.sources import (
    FxObservation,
    LicensePermission,
    MarketSession,
    SourceCalendar,
    SourceLicense,
    SourcePeriod,
    SourceProvenance,
)
from trading212_domain.values import require_utc
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    PortfolioSnapshotModel,
)
from trading212_persistence.source_models import FxObservationModel
from trading212_persistence.source_service import PostgresSourceService
from trading212_security.principals import Principal, Scope
from trading212_worker.materializer import PostgresCanonicalMaterializer
from trading212_worker.postgres_store import PostgresIngestionStore
from trading212_worker.synthetic import SyntheticIngestionProvider
from trading212_worker.synthetic_custody import SyntheticCustodyIngestionProvider
from trading212_worker.synthetic_custody_types import (
    CustodyAccountSnapshot,
    CustodyActivity,
    CustodyAsset,
    CustodyPosition,
)
from trading212_worker.synthetic_grants import seed_synthetic_grants


def fixture_id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, "trading212-portfolio-intelligence/browser-aggregation/" + name)


EUR_ACCOUNT_ID = fixture_id("eur-account")
USD_ACCOUNT_ID = fixture_id("usd-account")
EUR_ACCOUNT_NAME = "Aggregation EUR provider account"
USD_ACCOUNT_NAME = "Aggregation USD custody account"
FX_PROVIDER_NAME = "Synthetic aggregation FX"
FX_RATE = Decimal("0.8")
CURSOR_KEY = b"synthetic-browser-aggregation-fx-cursors-v1"


def aggregation_enabled(value: str) -> bool:
    if value not in {"0", "1"}:
        raise RuntimeError("The aggregation browser fixture selector must be 0 or 1.")
    return value == "1"


def _fixed_clock(at: datetime) -> Callable[[], datetime]:
    return lambda: at


def _custody(at: datetime) -> CustodyAccountSnapshot:
    usd = CurrencyCode("USD")
    asset = CustodyAsset(
        native_asset_key="aggregate-usd-equity",
        isin="XS0000000001",
        listing_code="AGG_USD",
        name="Synthetic Global Equity",
        quote_currency=usd,
    )
    opened = at - timedelta(days=1)
    return CustodyAccountSnapshot(
        account_id=USD_ACCOUNT_ID,
        currency=usd,
        valuation_at=at,
        cash_available=Decimal("30"),
        investments_value=Decimal("150"),
        investments_cost=Decimal("120"),
        unrealized_pnl=Decimal("30"),
        net_asset_value=Decimal("180"),
        assets=(asset,),
        positions=(
            CustodyPosition(
                asset=asset,
                opened_at=opened,
                units=Decimal("3"),
                last_quote=Decimal("50"),
                mean_acquisition_quote=Decimal("40"),
                native_market_value=Decimal("150"),
                native_cost_basis=Decimal("120"),
                native_unrealized_pnl=Decimal("30"),
                valuation_at=at,
            ),
        ),
        activity=(
            CustodyActivity(
                native_record_key="aggregate-deposit",
                kind="cash_in",
                booked_at=opened,
                published_at=opened,
                signed_cash=Decimal("150"),
                currency=usd,
            ),
            CustodyActivity(
                native_record_key="aggregate-buy",
                kind="asset_purchase",
                booked_at=opened,
                published_at=opened,
                signed_cash=Decimal("-120"),
                currency=usd,
            ),
        ),
    )


async def _fx(
    sessions: sessionmaker[Session], principal: Principal, at: datetime
) -> tuple[str, str]:
    """Persist one explicit synthetic quote through canonical typed source ingestion."""
    provider, license_id = fixture_id("fx-provider"), fixture_id("fx-license")
    quote_at = datetime.combine((at - timedelta(days=1)).date(), time(12), UTC)
    service = PostgresSourceService(
        sessions=sessions, cursor_signing_key=CURSOR_KEY, clock=lambda: at
    )
    await service.configure_source_provider(
        principal,
        SourceProviderRegistration(
            id=str(provider),
            key="synthetic-aggregation-fx",
            name=FX_PROVIDER_NAME,
            adapter_version="synthetic-aggregation-fx-v1",
            configuration_state=ProviderConfigurationState.CONFIGURED,
            synthetic=True,
            capabilities=(SourceCapability.FX_RATES,),
            supported_price_bases=(),
        ),
        idempotency_key="aggregation-browser-fx-provider",
        correlation_id="aggregation-browser",
    )
    license = SourceLicense(
        id=str(license_id),
        provider_id=str(provider),
        version="synthetic-aggregation-fx-1",
        effective_at=at - timedelta(days=2),
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=LicensePermission.ALLOWED,
        export=LicensePermission.ALLOWED,
        retention_days=30,
        attribution="Synthetic browser fixture only. No live provider or broker request.",
        evidence_key="synthetic-aggregation-fx-entitlement",
    )
    await service.register_source_license(
        principal,
        license,
        idempotency_key="aggregation-browser-fx-license",
        correlation_id="aggregation-browser",
    )
    calendar = SourceCalendar(
        id="synthetic-aggregation-fx-calendar",
        version="1",
        timezone="UTC",
        period=SourcePeriod(start=quote_at.date(), end=quote_at.date()),
        sessions=(MarketSession(session_date=quote_at.date(), close_at=quote_at),),
    )
    await service.register_source_calendar(
        principal,
        calendar,
        idempotency_key="aggregation-browser-fx-calendar",
        correlation_id="aggregation-browser",
    )
    usd, eur = CurrencyCode("USD"), CurrencyCode("EUR")
    observation = FxObservation(
        base=usd,
        quote=eur,
        session_date=quote_at.date(),
        effective_at=quote_at,
        rate=FX_RATE,
        batch_key="synthetic-aggregation-fixing",
    )
    request = FxRatesRequest(
        provider_id=str(provider),
        license_version_id=str(license_id),
        calendar_id=calendar.id,
        calendar_version=calendar.version,
        pairs=(FxPair(base=usd, quote=eur),),
        period=calendar.period,
        source_cutoff_at=at,
    )
    saved = await service.ingest_fx_rates(
        principal,
        request,
        (
            FxRatePage(
                provenance=SourceProvenance(
                    provider_id=str(provider),
                    license_version_id=str(license_id),
                    adapter_version="synthetic-aggregation-fx-v1",
                    schema_version="1",
                    source_revision="1",
                    revision_order=1,
                    effective_at=quote_at,
                    first_observed_at=at,
                    synthetic=True,
                ),
                period=calendar.period,
                coverage=assess_fx_coverage(
                    calendar, calendar.period, (observation,), pairs=((usd, eur),)
                ),
                observations=(observation,),
            ),
        ),
        idempotency_key="aggregation-browser-fx",
        correlation_id="aggregation-browser",
    )
    with sessions() as session:
        ids = tuple(
            session.scalars(
                select(FxObservationModel.id)
                .where(
                    FxObservationModel.owner_id == UUID(principal.owner_id),
                    FxObservationModel.snapshot_id == UUID(saved.id),
                )
                .limit(2)
            )
        )
        if len(ids) != 1:
            raise RuntimeError("Aggregation browser fixture requires one persisted FX reference.")
    return saved.id, str(ids[0])


async def seed_aggregation_browser_scenario(
    sessions: sessionmaker[Session], *, app_environment: str, at: datetime
) -> dict[str, str]:
    if app_environment != "test" or not aggregation_enabled(
        os.environ.get("T212PI_E2E_AGGREGATION", "0")
    ):
        raise RuntimeError(
            "Aggregation browser fixtures require explicit opt-in and the test environment."
        )
    at = require_utc(at)
    identity = build_synthetic_identity()
    scopes = frozenset(
        {
            Scope.PORTFOLIO_READ,
            Scope.ACTIVITY_READ,
            Scope.ANALYTICS_READ,
            Scope.AGGREGATE_READ,
            Scope.AGGREGATE_WRITE,
            Scope.TARGETS_WRITE,
        }
    )
    seed_synthetic_grants(sessions, app_environment="test", at=at, scopes=scopes)
    principal = Principal(
        principal_id=str(identity.principal.id),
        owner_id=str(identity.owner.id),
        issuer="local.synthetic",
        subject="synthetic-owner",
        scopes=scopes,
        authenticated_at=at - timedelta(seconds=1),
        expires_at=at + timedelta(hours=2),
    )
    connection = fixture_id("connection")
    with sessions() as session, session.begin():
        if session.get(BrokerConnectionModel, connection) is not None:
            raise RuntimeError("Aggregation browser fixture must seed a fresh disposable database.")
        session.add(
            BrokerConnectionModel(
                id=connection,
                owner_id=identity.owner.id,
                provider="synthetic",
                environment="synthetic",
                credential_reference=None,
                status="active",
            )
        )
        session.flush()
        for account, name, currency in (
            (EUR_ACCOUNT_ID, EUR_ACCOUNT_NAME, "EUR"),
            (USD_ACCOUNT_ID, USD_ACCOUNT_NAME, "USD"),
        ):
            session.add(
                BrokerAccountModel(
                    id=account,
                    connection_id=connection,
                    provider_account_id="browser-aggregate-" + currency.lower(),
                    account_type="invest",
                    base_currency=currency,
                    display_name=name,
                    status="active",
                    first_seen_at=at,
                    last_seen_at=at,
                )
            )
    eur_at, usd_at = at - timedelta(hours=2), at - timedelta(hours=1)
    providers: tuple[tuple[UUID, BrokerAccountDataProvider, datetime], ...] = (
        (EUR_ACCOUNT_ID, SyntheticIngestionProvider(clock=_fixed_clock(eur_at)), eur_at),
        (
            USD_ACCOUNT_ID,
            SyntheticCustodyIngestionProvider(_custody(usd_at), clock=_fixed_clock(usd_at)),
            usd_at,
        ),
    )
    for account, provider, observed in providers:
        run = await IngestionCoordinator(
            provider=provider,
            store=PostgresIngestionStore(
                sessions, provider="synthetic", materializer=PostgresCanonicalMaterializer()
            ),
            clock=_fixed_clock(observed),
        ).refresh(
            owner_id=str(identity.owner.id),
            account_id=str(account),
            mode=RunMode.FULL,
            idempotency_key="aggregation-browser-" + str(account),
            correlation_id="aggregation-browser",
        )
        if run.status is not RunStatus.SUCCEEDED:
            raise RuntimeError("Aggregation browser canonical ingestion did not succeed.")
    with sessions() as session:
        rows = tuple(
            session.scalars(
                select(PortfolioSnapshotModel)
                .where(
                    PortfolioSnapshotModel.broker_account_id.in_((EUR_ACCOUNT_ID, USD_ACCOUNT_ID))
                )
                .limit(3)
            )
        )
        if len(rows) != 2 or {row.broker_account_id for row in rows} != {
            EUR_ACCOUNT_ID,
            USD_ACCOUNT_ID,
        }:
            raise RuntimeError(
                "Aggregation browser fixture requires exactly two saved canonical snapshots."
            )
        snapshots = {row.broker_account_id: row for row in rows}
        # Return persisted clocks, never assumed adapter timestamps, to consumers.
        metadata = {
            "eur_account_id": str(EUR_ACCOUNT_ID),
            "usd_account_id": str(USD_ACCOUNT_ID),
            "eur_snapshot_id": str(snapshots[EUR_ACCOUNT_ID].id),
            "usd_snapshot_id": str(snapshots[USD_ACCOUNT_ID].id),
            "eur_valuation_at": snapshots[EUR_ACCOUNT_ID].valuation_at.isoformat(),
            "usd_valuation_at": snapshots[USD_ACCOUNT_ID].valuation_at.isoformat(),
            "source_cutoff_at": at.isoformat(),
        }
    fx_snapshot, fx_observation = await _fx(sessions, principal, at)
    return {
        **metadata,
        "fx_snapshot_id": fx_snapshot,
        "fx_observation_id": fx_observation,
        "fx_provider_id": str(fixture_id("fx-provider")),
        "fx_provider_name": FX_PROVIDER_NAME,
        "fx_base": "USD",
        "fx_quote": "EUR",
        "fx_rate": str(FX_RATE),
    }
