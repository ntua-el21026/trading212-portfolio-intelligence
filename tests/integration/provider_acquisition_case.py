"""Explicit synthetic authority installation in the reused PostgreSQL fixture."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from trading212_domain import CurrencyCode
from trading212_domain.sources import (
    MarketSession,
    PriceBasis,
    SourceCalendar,
    SourcePeriod,
    SourceSeries,
    SourceSeriesKind,
)
from trading212_persistence.acquisition_authority import grant_digest, mapping_digest, policy_digest
from trading212_persistence.acquisition_models import (
    ProviderAcquisitionMappingModel,
    ProviderAcquisitionPolicyModel,
    ProviderCapabilityGrantModel,
    ProviderCapabilityScopeModel,
)
from trading212_persistence.acquisition_records import AcquisitionCapability, AcquisitionSelection
from trading212_persistence.acquisition_store import PostgresAcquisitionStore
from trading212_persistence.models import InstrumentModel
from trading212_persistence.source_models import (
    MarketDataInstrumentModel,
    MarketDataProviderModel,
    MarketSourceSeriesModel,
    ProviderLicenseVersionModel,
    SourceCalendarModel,
    SourceCalendarSessionModel,
)
from trading212_persistence.source_store import digest
from trading212_worker.xray_fixture import XRAY_ACCOUNT_ID, xray_id

from tests.integration.test_scenario_runs_postgres import grant_scenario_identity
from tests.integration.test_xray_reads_postgres import XrayReadCase


@dataclass
class AcquisitionCase:
    xray: XrayReadCase
    store: PostgresAcquisitionStore
    selection: AcquisitionSelection
    grant: ProviderCapabilityGrantModel
    policy: ProviderAcquisitionPolicyModel
    mapping: ProviderAcquisitionMappingModel
    calendar: SourceCalendar
    series: SourceSeries | None


def acquisition_case(
    case: XrayReadCase,
    *,
    capability: AcquisitionCapability = AcquisitionCapability.DAILY_ADJUSTED,
    allowance: int | None = None,
) -> AcquisitionCase:
    at = datetime.now(UTC)
    grant_scenario_identity(case.sessions, case.principal, at)
    owner = UUID(case.principal.owner_id)
    fx = capability is AcquisitionCapability.REFERENCE_FX
    entity = capability in {
        AcquisitionCapability.NEWS_SENTIMENT,
        AcquisitionCapability.COMPANY_OVERVIEW,
    }
    provider_id, license_id = uuid4(), uuid4()
    mapping_id, scope_id, calendar_id = uuid4(), uuid4(), uuid4()
    day = (at - timedelta(days=1)).date()
    calendar = SourceCalendar(
        id=f"acq-calendar-{calendar_id.hex}",
        version="1",
        timezone="UTC",
        period=SourcePeriod(start=day, end=day),
        sessions=(MarketSession(session_date=day, close_at=datetime.combine(day, time(12), UTC)),),
    )
    series = None
    with case.sessions() as session, session.begin():
        instrument = session.scalar(
            select(InstrumentModel.id).where(
                InstrumentModel.id == UUID(xray_id("instrument/alpha-a"))
            )
        )
        assert instrument is not None
        provider = MarketDataProviderModel(
            id=provider_id,
            owner_id=owner,
            key="ecb" if fx else "alpha_vantage",
            name="Explicit synthetic provider contract fixture",
            adapter_version="premium_fixed_get_v1",
            configuration_state="configured",
            synthetic=False,
            revision=1,
            updated_at=at,
            created_at=at,
            capabilities=["fx_rates"] if fx else ["price_history"],
            supported_price_bases=[] if fx else ["raw_close"],
            freshness_policy_version=None,
            max_age_seconds=None,
        )
        session.add(provider)
        session.flush()
        session.add(
            ProviderLicenseVersionModel(
                id=license_id,
                owner_id=owner,
                provider_id=provider_id,
                version_number=1,
                version="fixture-v1",
                effective_at=at - timedelta(days=2),
                store_permission="allowed",
                display_permission="allowed",
                report_permission="allowed",
                export_permission="allowed",
                retention_days=1,
                attribution="Synthetic test only",
                evidence_key="synthetic-entitlement-evidence",
                created_at=at,
            )
        )
        session.add(
            SourceCalendarModel(
                id=calendar_id,
                owner_id=owner,
                key=calendar.id,
                version=calendar.version,
                timezone=calendar.timezone,
                period_start=day,
                period_end=day,
                content_digest=digest(calendar),
                created_at=at,
            )
        )
        session.flush()
        session.add(
            SourceCalendarSessionModel(
                id=uuid4(),
                owner_id=owner,
                calendar_id=calendar_id,
                session_date=day,
                close_at=calendar.sessions[0].close_at,
                created_at=at,
            )
        )
        if not fx:
            market = MarketDataInstrumentModel(
                id=mapping_id,
                owner_id=owner,
                provider_id=provider_id,
                provider_key="ALPHA",
                version="1",
                state="resolved",
                instrument_id=instrument,
                listing_id=None,
                identifier_kind="provider_key",
                identifier_value="ALPHA",
                identifier_mic=None,
                currency="EUR",
                asset_type="equity",
                evidence_key="synthetic-mapping",
                valid_from=at - timedelta(days=2),
                valid_to=None,
                content_digest="c" * 64,
                created_at=at,
            )
            session.add(market)
            session.flush()
        scope = ProviderCapabilityScopeModel(
            id=scope_id,
            owner_id=owner,
            provider_id=provider_id,
            capability=capability.value,
            subject_kind="reference_fx" if fx else ("entity" if entity else "instrument"),
            subject_id=None if fx else (UUID(xray_id("entity/alpha")) if entity else instrument),
            created_at=at,
        )
        session.add(scope)
        session.flush()
        grant = ProviderCapabilityGrantModel(
            id=uuid4(),
            owner_id=owner,
            provider_id=provider_id,
            scope_id=scope.id,
            version_number=1,
            license_version_id=license_id,
            effective_at=at - timedelta(days=1),
            expires_at=at + timedelta(days=1),
            store_allowed=True,
            display_allowed=True,
            report_allowed=True,
            export_allowed=True,
            daily_allowance=allowance if allowance is not None else (24 if fx else 25),
            evidence_key="synthetic-license-approval",
            content_digest="0" * 64,
            created_at=at,
        )
        grant.content_digest = grant_digest(grant)
        policy = ProviderAcquisitionPolicyModel(
            id=uuid4(),
            owner_id=owner,
            provider_id=provider_id,
            version_number=1,
            effective_at=at - timedelta(days=1),
            expires_at=at + timedelta(days=1),
            enabled=True,
            daily_allowance=24 if fx else 25,
            evidence_key="synthetic-positive-allowance",
            content_digest="0" * 64,
            created_at=at,
        )
        policy.content_digest = policy_digest(policy)
        session.add_all([grant, policy])
        session.flush()
        if capability is AcquisitionCapability.DAILY_ADJUSTED:
            series_id = uuid4()
            series = SourceSeries(
                id=str(series_id),
                owner_id=str(owner),
                provider_id=str(provider_id),
                license_version_id=str(license_id),
                kind=SourceSeriesKind.SECURITY_PRICE,
                provider_key="ALPHA",
                mapping_version="1",
                basis=PriceBasis.RAW_CLOSE,
                currency=CurrencyCode("EUR"),
                calendar_id=calendar.id,
                calendar_version=calendar.version,
                mapping_id=str(mapping_id),
                instrument_id=str(instrument),
                listing_id=None,
            )
            session.add(
                MarketSourceSeriesModel(
                    id=series_id,
                    owner_id=owner,
                    provider_id=provider_id,
                    license_version_id=license_id,
                    calendar_id=calendar_id,
                    mapping_id=mapping_id,
                    kind="security_price",
                    provider_key="ALPHA",
                    mapping_version="1",
                    instrument_id=instrument,
                    listing_id=None,
                    basis="raw_close",
                    currency="EUR",
                    content_digest=digest(series),
                    created_at=at,
                )
            )
            session.flush()
        mapping = ProviderAcquisitionMappingModel(
            id=uuid4(),
            owner_id=owner,
            scope_id=scope.id,
            version_number=1,
            market_mapping_id=None if fx else mapping_id,
            calendar_id=calendar_id,
            source_series_id=None if series is None else UUID(series.id),
            effective_at=at - timedelta(days=1),
            expires_at=at + timedelta(days=1),
            evidence_key="synthetic-canonical-binding",
            content_digest="0" * 64,
            created_at=at,
        )
        mapping.content_digest = mapping_digest(mapping)
        session.add(mapping)
        session.flush()
        for row in (grant, policy, mapping):
            session.expunge(row)
    selection = AcquisitionSelection(
        owner_id=owner,
        account_id=UUID(XRAY_ACCOUNT_ID),
        request_id=uuid4(),
        mapping_version_id=mapping.id,
        capability=capability,
    )
    return AcquisitionCase(
        case,
        PostgresAcquisitionStore(sessions=case.sessions, principal=case.principal, enabled=True),
        selection,
        grant,
        policy,
        mapping,
        calendar,
        series,
    )
