"""Private persistence values; no transport, credentials, provider payloads or URLs."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from trading212_domain import CurrencyCode, require_utc
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import SourceLicense

ACQUISITION_SOURCE_PERMISSION_MAX_ROWS = 12


class AcquisitionCapability(StrEnum):
    DAILY_ADJUSTED = "daily_adjusted"
    ETF_PROFILE = "etf_profile"
    COMPANY_OVERVIEW = "company_overview"
    NEWS_SENTIMENT = "news_sentiment"
    REFERENCE_FX = "reference_fx"


class AcquisitionOutcome(StrEnum):
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


RETRYABLE = frozenset(
    {
        AcquisitionOutcome.RATE_LIMITED,
        AcquisitionOutcome.TIMEOUT,
        AcquisitionOutcome.TRANSIENT_FAILURE,
    }
)


class AcquisitionStorageDenied(RuntimeError):
    def __init__(self) -> None:
        super().__init__("The provider acquisition is not authorized or no longer available.")


def require_digest(value: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise AcquisitionStorageDenied()
    return value


def metadata_digest(kind: str, value: object) -> str:
    return hashlib.sha256(
        (f"t212pi.acquisition.{kind}.v1\n" + canonical_json(value)).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionSelection:
    owner_id: UUID
    account_id: UUID
    request_id: UUID
    mapping_version_id: UUID
    capability: AcquisitionCapability

    def __post_init__(self) -> None:
        if any(
            type(value) is not UUID
            for value in (self.owner_id, self.account_id, self.request_id, self.mapping_version_id)
        ):
            raise AcquisitionStorageDenied()
        if type(self.capability) is not AcquisitionCapability:
            raise AcquisitionStorageDenied()


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionAuthorityBasis:
    owner_id: UUID
    account_id: UUID
    mapping_version_id: UUID
    mapping_digest: str
    provider_id: UUID
    provider_key: str
    capability: AcquisitionCapability
    policy_version_id: UUID
    policy_digest: str
    grant_id: UUID
    grant_digest: str
    license: SourceLicense
    effective_at: datetime
    expires_at: datetime
    daily_allowance: int
    symbol: str | None
    price_currency: CurrencyCode | None
    instrument_id: UUID | None
    entity_id: UUID | None
    calendar_id: UUID | None
    source_series_id: UUID | None
    canonical_market_mapping_id: UUID | None

    def __post_init__(self) -> None:
        for digest in (self.mapping_digest, self.policy_digest, self.grant_digest):
            require_digest(digest)
        for name in ("effective_at", "expires_at"):
            object.__setattr__(self, name, require_utc(getattr(self, name)))
        if self.provider_key not in {"alpha_vantage", "ecb"}:
            raise AcquisitionStorageDenied()
        cap = 24 if self.provider_key == "ecb" else 25
        if type(self.daily_allowance) is not int or not 1 <= self.daily_allowance <= cap:
            raise AcquisitionStorageDenied()
        if self.expires_at <= self.effective_at or self.license.provider_id != str(
            self.provider_id
        ):
            raise AcquisitionStorageDenied()

    def identity(self) -> tuple[object, ...]:
        """Operational allowance/current clamps may shrink; original pins may not change."""
        return (
            self.owner_id,
            self.account_id,
            self.mapping_version_id,
            self.mapping_digest,
            self.provider_id,
            self.provider_key,
            self.capability,
            self.policy_version_id,
            self.policy_digest,
            self.grant_id,
            self.grant_digest,
            self.license,
            self.symbol,
            self.price_currency,
            self.instrument_id,
            self.entity_id,
            self.calendar_id,
            self.source_series_id,
            self.canonical_market_mapping_id,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionPublicationClock:
    """Body-receipt time, distinct from later attempt finish and SQL publication."""

    acquired_at: datetime
    first_known_at: datetime
    expires_at: datetime
    content_digest: str

    def __post_init__(self) -> None:
        require_digest(self.content_digest)
        for name in ("acquired_at", "first_known_at", "expires_at"):
            object.__setattr__(self, name, require_utc(getattr(self, name)))
        if (
            self.acquired_at != self.first_known_at
            or not self.acquired_at < self.expires_at <= self.acquired_at + timedelta(days=30)
        ):
            raise AcquisitionStorageDenied()


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionAttemptReceipt:
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
        require_digest(self.request_digest)
        if any(
            type(value) is not UUID
            for value in (self.id, self.request_id, self.owner_id, self.provider_id)
        ):
            raise AcquisitionStorageDenied()
        for name in ("first_started_at", "reserved_at", "deadline", "lease_expires_at"):
            object.__setattr__(self, name, require_utc(getattr(self, name)))
        if (
            type(self.ordinal) is not int
            or not 1 <= self.ordinal <= 3
            or not self.first_started_at
            <= self.reserved_at
            < self.lease_expires_at
            <= self.deadline
            or self.deadline > self.first_started_at + timedelta(seconds=20)
        ):
            raise AcquisitionStorageDenied()


def retry_due(
    outcome: AcquisitionOutcome | None,
    ordinal: int,
    *,
    observed_at: datetime,
    deadline: datetime,
    requested: datetime | None,
) -> datetime | None:
    """Validate scheduled retry; never sleep or restart the original request clock."""
    if requested is None:
        return None
    if outcome not in RETRYABLE or ordinal >= 3:
        raise AcquisitionStorageDenied()
    due = require_utc(requested)
    minimum = observed_at + timedelta(seconds=ordinal)
    if due < minimum or due > observed_at + timedelta(seconds=60) or due >= deadline:
        raise AcquisitionStorageDenied()
    return due
