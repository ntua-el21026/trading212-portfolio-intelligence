"""Current durable account, canonical mapping and original/current licence authority."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application.research import RESEARCH_WRITE_SCOPES
from trading212_domain import CurrencyCode
from trading212_domain.sources import SourceUse
from trading212_security.principals import Principal, Scope

from .acquisition_models import (
    ProviderAcquisitionMappingModel as Mapping,
)
from .acquisition_models import (
    ProviderAcquisitionPolicyModel as Policy,
)
from .acquisition_models import (
    ProviderCapabilityGrantModel as Grant,
)
from .acquisition_models import (
    ProviderCapabilityScopeModel as CapabilityScope,
)
from .acquisition_records import (
    AcquisitionAuthorityBasis,
    AcquisitionCapability,
    AcquisitionSelection,
    AcquisitionStorageDenied,
    metadata_digest,
)
from .models import InstrumentModel
from .report_authorization import ReportAuthorization, authorize_report_request
from .source_models import (
    MarketDataInstrumentModel,
    MarketDataProviderModel,
    MarketSourceSeriesModel,
    ProviderLicenseVersionModel,
    SourceCalendarModel,
)
from .source_store import license_view
from .xray_catalog_models import EconomicEntityModel


def grant_digest(row: Grant) -> str:
    return metadata_digest(
        "grant",
        {
            name: getattr(row, name)
            for name in (
                "id",
                "owner_id",
                "provider_id",
                "scope_id",
                "version_number",
                "license_version_id",
                "effective_at",
                "expires_at",
                "store_allowed",
                "display_allowed",
                "report_allowed",
                "export_allowed",
                "daily_allowance",
                "evidence_key",
            )
        },
    )


def policy_digest(row: Policy) -> str:
    return metadata_digest(
        "policy",
        {
            name: getattr(row, name)
            for name in (
                "id",
                "owner_id",
                "provider_id",
                "version_number",
                "effective_at",
                "expires_at",
                "enabled",
                "daily_allowance",
                "evidence_key",
            )
        },
    )


def mapping_digest(row: Mapping) -> str:
    return metadata_digest(
        "mapping",
        {
            name: getattr(row, name)
            for name in (
                "id",
                "owner_id",
                "scope_id",
                "version_number",
                "market_mapping_id",
                "calendar_id",
                "source_series_id",
                "effective_at",
                "expires_at",
                "evidence_key",
            )
        },
    )


def acquisition_auth(
    session: Session, principal: Principal, selection: AcquisitionSelection, *, now: datetime
) -> ReportAuthorization:
    scopes = frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.TARGETS_WRITE})
    if selection.capability in {
        AcquisitionCapability.COMPANY_OVERVIEW,
        AcquisitionCapability.NEWS_SENTIMENT,
    }:
        scopes = scopes | RESEARCH_WRITE_SCOPES
    if UUID(principal.owner_id) != selection.owner_id:
        raise AcquisitionStorageDenied()
    return authorize_report_request(
        session, principal, account_id=selection.account_id, required_scopes=scopes, now=now
    )


def resolve_acquisition(
    session: Session,
    principal: Principal,
    selection: AcquisitionSelection,
    *,
    now: datetime,
    pinned: AcquisitionAuthorityBasis | None = None,
) -> tuple[ReportAuthorization, AcquisitionAuthorityBasis]:
    auth = acquisition_auth(session, principal, selection, now=now)
    mapping = session.scalar(
        select(Mapping)
        .where(Mapping.owner_id == auth.owner_id, Mapping.id == selection.mapping_version_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        mapping is None
        or not mapping.effective_at <= now < mapping.expires_at
        or mapping_digest(mapping) != mapping.content_digest
    ):
        raise AcquisitionStorageDenied()
    scope = session.scalar(
        select(CapabilityScope).where(
            CapabilityScope.owner_id == auth.owner_id, CapabilityScope.id == mapping.scope_id
        )
    )
    if scope is None or scope.capability != selection.capability.value:
        raise AcquisitionStorageDenied()
    current_mapping = session.scalar(
        select(Mapping.id)
        .where(
            Mapping.owner_id == auth.owner_id,
            Mapping.scope_id == scope.id,
            Mapping.effective_at <= now,
        )
        .order_by(Mapping.effective_at.desc(), Mapping.version_number.desc(), Mapping.id.desc())
        .limit(1)
    )
    provider = session.scalar(
        select(MarketDataProviderModel)
        .where(
            MarketDataProviderModel.owner_id == auth.owner_id,
            MarketDataProviderModel.id == scope.provider_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    expected_provider = (
        "ecb" if selection.capability is AcquisitionCapability.REFERENCE_FX else "alpha_vantage"
    )
    if (
        current_mapping != mapping.id
        or provider is None
        or provider.key != expected_provider
        or provider.configuration_state != "configured"
    ):
        raise AcquisitionStorageDenied()
    current_policy = session.scalar(
        select(Policy)
        .where(
            Policy.owner_id == auth.owner_id,
            Policy.provider_id == provider.id,
            Policy.effective_at <= now,
        )
        .order_by(Policy.effective_at.desc(), Policy.version_number.desc(), Policy.id.desc())
        .limit(1)
        .with_for_update(read=True)
    )
    current_grant = session.scalar(
        select(Grant)
        .where(
            Grant.owner_id == auth.owner_id, Grant.scope_id == scope.id, Grant.effective_at <= now
        )
        .order_by(Grant.effective_at.desc(), Grant.version_number.desc(), Grant.id.desc())
        .limit(1)
        .with_for_update(read=True)
    )
    policy = (
        current_policy
        if pinned is None
        else session.scalar(
            select(Policy).where(
                Policy.owner_id == auth.owner_id, Policy.id == pinned.policy_version_id
            )
        )
    )
    grant = (
        current_grant
        if pinned is None
        else session.scalar(
            select(Grant).where(Grant.owner_id == auth.owner_id, Grant.id == pinned.grant_id)
        )
    )
    if any(value is None for value in (current_policy, current_grant, policy, grant)):
        raise AcquisitionStorageDenied()
    assert (
        current_policy is not None
        and current_grant is not None
        and policy is not None
        and grant is not None
    )
    for value in (policy, current_policy):
        if (
            value.provider_id != provider.id
            or not value.effective_at <= now < value.expires_at
            or not value.enabled
            or value.daily_allowance <= 0
            or policy_digest(value) != value.content_digest
        ):
            raise AcquisitionStorageDenied()
    for retained_grant in (grant, current_grant):
        if (
            retained_grant.scope_id != scope.id
            or retained_grant.provider_id != provider.id
            or not retained_grant.effective_at <= now < retained_grant.expires_at
            or not retained_grant.store_allowed
            or not retained_grant.display_allowed
            or retained_grant.daily_allowance <= 0
            or grant_digest(retained_grant) != retained_grant.content_digest
        ):
            raise AcquisitionStorageDenied()
    original_license = session.scalar(
        select(ProviderLicenseVersionModel).where(
            ProviderLicenseVersionModel.owner_id == auth.owner_id,
            ProviderLicenseVersionModel.id == grant.license_version_id,
        )
    )
    current_license = session.scalar(
        select(ProviderLicenseVersionModel)
        .where(
            ProviderLicenseVersionModel.owner_id == auth.owner_id,
            ProviderLicenseVersionModel.provider_id == provider.id,
            ProviderLicenseVersionModel.effective_at <= now,
        )
        .order_by(
            ProviderLicenseVersionModel.effective_at.desc(),
            ProviderLicenseVersionModel.version_number.desc(),
            ProviderLicenseVersionModel.id.desc(),
        )
        .limit(1)
    )
    if (
        original_license is None
        or current_license is None
        or current_grant.license_version_id != current_license.id
    ):
        raise AcquisitionStorageDenied()
    for retained_license in (original_license, current_license):
        if (
            retained_license.provider_id != provider.id
            or retained_license.effective_at > now
            or retained_license.retention_days is None
            or retained_license.retention_days < 1
            or not all(
                license_view(retained_license).permits(use)
                for use in (SourceUse.STORE, SourceUse.DISPLAY)
            )
        ):
            raise AcquisitionStorageDenied()
    market = None
    if mapping.market_mapping_id is not None:
        market = session.scalar(
            select(MarketDataInstrumentModel).where(
                MarketDataInstrumentModel.owner_id == auth.owner_id,
                MarketDataInstrumentModel.provider_id == provider.id,
                MarketDataInstrumentModel.id == mapping.market_mapping_id,
            )
        )
        if (
            market is None
            or market.state != "resolved"
            or market.instrument_id is None
            or market.valid_from > now
            or (market.valid_to is not None and market.valid_to <= now)
        ):
            raise AcquisitionStorageDenied()
    if selection.capability is not AcquisitionCapability.REFERENCE_FX and market is None:
        raise AcquisitionStorageDenied()
    if scope.subject_kind == "entity":
        if (
            session.scalar(
                select(EconomicEntityModel.id).where(
                    EconomicEntityModel.owner_id == auth.owner_id,
                    EconomicEntityModel.id == scope.subject_id,
                )
            )
            is None
        ):
            raise AcquisitionStorageDenied()
    elif scope.subject_kind == "instrument" and (
        market is None
        or market.instrument_id != scope.subject_id
        or session.get(InstrumentModel, scope.subject_id) is None
    ):
        raise AcquisitionStorageDenied()
    if (
        mapping.calendar_id is not None
        and session.scalar(
            select(SourceCalendarModel.id).where(
                SourceCalendarModel.owner_id == auth.owner_id,
                SourceCalendarModel.id == mapping.calendar_id,
            )
        )
        is None
    ):
        raise AcquisitionStorageDenied()
    if mapping.source_series_id is not None:
        series = session.scalar(
            select(MarketSourceSeriesModel).where(
                MarketSourceSeriesModel.owner_id == auth.owner_id,
                MarketSourceSeriesModel.id == mapping.source_series_id,
            )
        )
        if (
            series is None
            or market is None
            or (
                series.provider_id,
                series.mapping_id,
                series.calendar_id,
                series.currency,
                series.instrument_id,
            )
            != (provider.id, market.id, mapping.calendar_id, market.currency, market.instrument_id)
            or series.basis != "raw_close"
            or series.license_version_id != original_license.id
        ):
            raise AcquisitionStorageDenied()
    basis = AcquisitionAuthorityBasis(
        owner_id=auth.owner_id,
        account_id=auth.account_id,
        mapping_version_id=mapping.id,
        mapping_digest=mapping.content_digest,
        provider_id=provider.id,
        provider_key=provider.key,
        capability=selection.capability,
        policy_version_id=policy.id,
        policy_digest=policy.content_digest,
        grant_id=grant.id,
        grant_digest=grant.content_digest,
        license=license_view(original_license),
        effective_at=max(
            mapping.effective_at,
            policy.effective_at,
            grant.effective_at,
            original_license.effective_at,
        ),
        expires_at=min(
            mapping.expires_at,
            policy.expires_at,
            grant.expires_at,
            current_policy.expires_at,
            current_grant.expires_at,
        ),
        daily_allowance=min(
            24 if provider.key == "ecb" else 25,
            policy.daily_allowance,
            current_policy.daily_allowance,
            grant.daily_allowance,
            current_grant.daily_allowance,
        ),
        symbol=None if market is None else market.provider_key,
        price_currency=None if market is None else CurrencyCode(market.currency),
        instrument_id=None if market is None else market.instrument_id,
        entity_id=scope.subject_id if scope.subject_kind == "entity" else None,
        calendar_id=mapping.calendar_id,
        source_series_id=mapping.source_series_id,
        canonical_market_mapping_id=mapping.market_mapping_id,
    )
    if pinned is not None and (
        basis.identity() != pinned.identity() or pinned.expires_at > basis.expires_at
    ):
        raise AcquisitionStorageDenied()
    return auth, basis
