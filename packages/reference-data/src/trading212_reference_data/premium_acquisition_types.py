"""Closed private acquisition commands and trusted authorization/attempt ports."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from trading212_domain import CurrencyCode, require_utc
from trading212_domain.sources import SourceLicense, SourcePeriod, SourceUse

ADAPTER_VERSION = "premium_fixed_get_v1"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.:-]{0,39}")


class AcquisitionCapability(StrEnum):
    DAILY_ADJUSTED = "daily_adjusted"
    ETF_PROFILE = "etf_profile"
    COMPANY_OVERVIEW = "company_overview"
    NEWS_SENTIMENT = "news_sentiment"
    REFERENCE_FX = "reference_fx"


class AcquisitionFailureCode(StrEnum):
    NOT_CONFIGURED = "not_configured"
    ACCESS_DENIED = "access_denied"
    LICENSE_DENIED = "license_denied"
    AUTHENTICATION_FAILED = "authentication_failed"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    TRANSIENT_FAILURE = "transient_failure"
    INVALID_SCHEMA = "invalid_schema"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED = "unsupported"
    PERMANENT_FAILURE = "permanent_failure"
    ATTEMPT_FENCE_LOST = "attempt_fence_lost"


class AcquisitionRejected(ValueError):
    def __init__(
        self, code: AcquisitionFailureCode = AcquisitionFailureCode.INVALID_SCHEMA
    ) -> None:
        self.code = code
        super().__init__("The fixed provider acquisition was rejected.")


@dataclass(frozen=True, slots=True, kw_only=True)
class _Command:
    owner_id: UUID
    account_id: UUID
    request_id: UUID
    mapping_version_id: UUID

    def __post_init__(self) -> None:
        if any(
            type(value) is not UUID
            for value in (
                self.owner_id,
                self.account_id,
                self.request_id,
                self.mapping_version_id,
            )
        ):
            raise AcquisitionRejected()


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquireDailyAdjusted(_Command):
    period: SourcePeriod

    def __post_init__(self) -> None:
        _Command.__post_init__(self)
        if (
            type(self.period) is not SourcePeriod
            or (self.period.end - self.period.start).days > 3660
        ):
            raise AcquisitionRejected()


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquireEtfProfile(_Command):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquireCompanyOverview(_Command):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquireNewsSentiment(_Command):
    time_from: datetime
    time_to: datetime
    limit: int = 100

    def __post_init__(self) -> None:
        _Command.__post_init__(self)
        for name in ("time_from", "time_to"):
            object.__setattr__(self, name, require_utc(getattr(self, name)))
        if (
            not self.time_from < self.time_to
            or self.time_to - self.time_from > timedelta(days=3660)
            or any(value.second or value.microsecond for value in (self.time_from, self.time_to))
            or type(self.limit) is not int
            or not 1 <= self.limit <= 100
        ):
            raise AcquisitionRejected()


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquireEcbReferenceFx(_Command):
    pass


type AcquisitionCommand = (
    AcquireDailyAdjusted
    | AcquireEtfProfile
    | AcquireCompanyOverview
    | AcquireNewsSentiment
    | AcquireEcbReferenceFx
)


def capability(command: AcquisitionCommand) -> AcquisitionCapability:
    kinds = {
        AcquireDailyAdjusted: AcquisitionCapability.DAILY_ADJUSTED,
        AcquireEtfProfile: AcquisitionCapability.ETF_PROFILE,
        AcquireCompanyOverview: AcquisitionCapability.COMPANY_OVERVIEW,
        AcquireNewsSentiment: AcquisitionCapability.NEWS_SENTIMENT,
        AcquireEcbReferenceFx: AcquisitionCapability.REFERENCE_FX,
    }
    result = kinds.get(type(command))
    if result is None:
        raise AcquisitionRejected()
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionPermit:
    owner_id: UUID
    account_id: UUID
    mapping_version_id: UUID
    mapping_digest: str
    provider_id: UUID
    capability: AcquisitionCapability
    policy_version_id: UUID
    policy_digest: str
    grant_id: UUID
    grant_digest: str
    license: SourceLicense
    effective_at: datetime
    expires_at: datetime
    symbol: str | None = None
    price_currency: CurrencyCode | None = None
    instrument_id: UUID | None = None
    canonical_market_mapping_id: UUID | None = None
    entity_id: UUID | None = None
    credential_reference: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not UUID
                for value in (
                    self.owner_id,
                    self.account_id,
                    self.mapping_version_id,
                    self.provider_id,
                    self.policy_version_id,
                    self.grant_id,
                )
            )
            or any(
                value is not None and type(value) is not UUID
                for value in (
                    self.instrument_id,
                    self.canonical_market_mapping_id,
                    self.entity_id,
                )
            )
            or any(
                type(value) is not str or not _DIGEST.fullmatch(value)
                for value in (
                    self.mapping_digest,
                    self.policy_digest,
                    self.grant_digest,
                )
            )
        ):
            raise AcquisitionRejected()
        for name in ("effective_at", "expires_at"):
            object.__setattr__(self, name, require_utc(getattr(self, name)))
        if (
            type(self.capability) is not AcquisitionCapability
            or type(self.license) is not SourceLicense
            or self.license.provider_id != str(self.provider_id)
            or self.expires_at <= self.effective_at
            or not all(self.license.permits(use) for use in (SourceUse.STORE, SourceUse.DISPLAY))
        ):
            raise AcquisitionRejected(AcquisitionFailureCode.LICENSE_DENIED)
        if self.price_currency is not None and type(self.price_currency) is not CurrencyCode:
            raise AcquisitionRejected()
        if self.capability is AcquisitionCapability.REFERENCE_FX:
            if any(
                value is not None
                for value in (
                    self.symbol,
                    self.price_currency,
                    self.credential_reference,
                    self.instrument_id,
                    self.canonical_market_mapping_id,
                    self.entity_id,
                )
            ):
                raise AcquisitionRejected()
        elif (
            type(self.symbol) is not str
            or not _SYMBOL.fullmatch(self.symbol)
            or self.credential_reference
            != f"reference-data/alpha-vantage/{self.owner_id}/{self.provider_id}"
        ):
            raise AcquisitionRejected()
        if self.capability in {
            AcquisitionCapability.DAILY_ADJUSTED,
            AcquisitionCapability.COMPANY_OVERVIEW,
        } and (type(self.price_currency) is not CurrencyCode or self.instrument_id is None):
            raise AcquisitionRejected()
        if (
            self.capability is AcquisitionCapability.DAILY_ADJUSTED
            and self.canonical_market_mapping_id is None
        ):
            raise AcquisitionRejected()
        if (
            self.capability
            in {AcquisitionCapability.COMPANY_OVERVIEW, AcquisitionCapability.NEWS_SENTIMENT}
            and self.entity_id is None
        ):
            raise AcquisitionRejected()

    def permits(self, command: AcquisitionCommand, now: datetime) -> bool:
        return (
            (self.owner_id, self.account_id, self.mapping_version_id, self.capability)
            == (
                command.owner_id,
                command.account_id,
                command.mapping_version_id,
                capability(command),
            )
            and self.effective_at <= now < self.expires_at
            and self.license.effective_at <= now
            and self.license.retention_days is not None
            and self.license.retention_days > 0
        )


@dataclass(frozen=True, slots=True, repr=False)
class AlphaVantageCredential:
    _value: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self._value) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", self._value):
            raise AcquisitionRejected(AcquisitionFailureCode.AUTHENTICATION_FAILED)

    def __repr__(self) -> str:
        return "AlphaVantageCredential(redacted=True)"

    def __str__(self) -> str:
        return "[REDACTED]"

    def reveal(self) -> str:
        return self._value


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionAttempt:
    id: UUID
    request_id: UUID
    owner_id: UUID
    provider_id: UUID
    request_digest: str
    ordinal: int
    first_started_at: datetime
    reserved_at: datetime
    deadline: datetime
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not UUID
                for value in (self.id, self.request_id, self.owner_id, self.provider_id)
            )
            or type(self.request_digest) is not str
            or not _DIGEST.fullmatch(self.request_digest)
            or type(self.ordinal) is not int
            or not 1 <= self.ordinal <= 3
        ):
            raise AcquisitionRejected()
        for name in ("first_started_at", "reserved_at", "deadline", "lease_expires_at"):
            object.__setattr__(self, name, require_utc(getattr(self, name)))
        if not (
            self.first_started_at
            <= self.reserved_at
            < self.deadline
            <= self.first_started_at + timedelta(seconds=20)
            and self.reserved_at < self.lease_expires_at <= self.deadline
        ):
            raise AcquisitionRejected()


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionFailure:
    code: AcquisitionFailureCode
    capability: AcquisitionCapability
    request_id: UUID
    retry_at: datetime | None = None
    attempt_id: UUID | None = None


class AcquisitionAuthority(Protocol):
    async def resolve(
        self, command: AcquisitionCommand, *, now: datetime
    ) -> AcquisitionPermit | None:
        """Resolve current owned-account/mapping/provider/policy/license/grant authority."""
        ...

    async def recheck(
        self, command: AcquisitionCommand, permit: AcquisitionPermit, *, now: datetime
    ) -> bool:
        """Recheck pinned/current IDs and original lifetimes without extending clocks."""
        ...


class AcquisitionCredentialPort(Protocol):
    async def resolve_alpha_vantage_credential(
        self, owner_id: UUID, provider_id: UUID, reference: str
    ) -> AlphaVantageCredential | None: ...


class AcquisitionAttemptPort(Protocol):
    async def reserve(
        self,
        command: AcquisitionCommand,
        permit: AcquisitionPermit,
        *,
        request_digest: str,
        now: datetime,
    ) -> AcquisitionAttempt | None:
        """Reserve actual allowance, one in-flight slot and the original retry deadline."""
        ...

    async def finish(
        self,
        attempt: AcquisitionAttempt,
        *,
        outcome: AcquisitionFailureCode | None,
        observed_at: datetime,
        retry_at: datetime | None,
    ) -> bool:
        "Fence this exact attempt and persist sanitized outcome/scheduled retry; no raw URL/body."
        ...
