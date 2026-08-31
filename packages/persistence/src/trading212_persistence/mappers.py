"""Explicit domain-to-persistence mappers; provider DTOs never enter this layer."""

from __future__ import annotations

from trading212_domain import (
    BrokerAccount,
    BrokerConnection,
    Instant,
    Instrument,
    Listing,
    Owner,
    Principal,
)

from .models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    InstrumentModel,
    ListingModel,
    OwnerModel,
    PrincipalModel,
)


def owner_to_model(value: Owner) -> OwnerModel:
    return OwnerModel(
        id=value.id,
        display_name=value.display_name,
        created_at=value.created_at.value,
        updated_at=value.created_at.value,
    )


def principal_to_model(value: Principal) -> PrincipalModel:
    return PrincipalModel(
        id=value.id,
        owner_id=value.owner_id,
        issuer=value.issuer,
        subject=value.subject,
        status=value.status.value,
        created_at=value.created_at.value,
    )


def connection_to_model(value: BrokerConnection) -> BrokerConnectionModel:
    return BrokerConnectionModel(
        id=value.id,
        owner_id=value.owner_id,
        provider=value.provider.value,
        environment=value.environment.value,
        credential_reference=value.credential_reference,
        status=value.status.value,
        created_at=value.created_at.value,
        updated_at=value.updated_at.value,
    )


def account_to_model(value: BrokerAccount) -> BrokerAccountModel:
    return BrokerAccountModel(
        id=value.id,
        connection_id=value.connection_id,
        provider_account_id=value.provider_account_id,
        account_type=value.account_type,
        base_currency=value.base_currency.value,
        display_name=value.display_name,
        status=value.status.value,
        first_seen_at=value.first_seen_at.value,
        last_seen_at=value.last_seen_at.value,
        created_at=value.first_seen_at.value,
        updated_at=value.last_seen_at.value,
    )


def instrument_to_model(value: Instrument, *, observed_at: Instant) -> InstrumentModel:
    return InstrumentModel(
        id=value.id,
        canonical_name=value.canonical_name,
        instrument_type=value.instrument_type,
        isin=value.isin,
        created_at=observed_at.value,
        updated_at=observed_at.value,
    )


def listing_to_model(value: Listing) -> ListingModel:
    return ListingModel(
        id=value.id,
        instrument_id=value.instrument_id,
        provider=value.provider.value,
        environment=value.environment.value,
        provider_instrument_id=value.provider_instrument_id,
        ticker=value.ticker,
        exchange_mic=value.exchange_mic,
        exchange_id=value.exchange_id,
        trading_currency=value.trading_currency.value,
        status=value.status.value,
        valid_from=value.valid_from.value,
        valid_to=None if value.valid_to is None else value.valid_to.value,
        created_at=value.valid_from.value,
        updated_at=value.valid_from.value,
    )
