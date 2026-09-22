"""Fixed metadata-only premium readiness; neither configuration nor status grants IO."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from trading212_domain import require_utc
from trading212_security.principals import Principal, Scope

PROVIDER_STATUS_SCOPES = frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ})


class PremiumProvider(StrEnum):
    ALPHA_VANTAGE = "alpha_vantage"
    ECB = "ecb"


class PremiumCapability(StrEnum):
    DAILY_ADJUSTED = "daily_adjusted"
    ETF_PROFILE = "etf_profile"
    COMPANY_OVERVIEW = "company_overview"
    NEWS_SENTIMENT = "news_sentiment"
    REFERENCE_FX = "reference_fx"


class PremiumReadiness(StrEnum):
    NOT_CONFIGURED = "not_configured"
    BLOCKED_EXTERNAL = "blocked_external"
    READY_UNVERIFIED = "ready_unverified"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class PremiumStatusReason(StrEnum):
    OUTBOUND_DISABLED = "outbound_disabled"
    PROVIDER_CONFIGURATION_REQUIRED = "provider_configuration_required"
    CREDENTIAL_CONFIGURATION_REQUIRED = "credential_configuration_required"
    CAPABILITY_RIGHTS_REQUIRED = "capability_rights_required"
    RESEARCH_SCOPE_REQUIRED = "research_scope_required"
    ACQUISITION_POLICY_REQUIRED = "acquisition_policy_required"
    CANONICAL_METADATA_UNAVAILABLE = "canonical_metadata_unavailable"
    METADATA_ELIGIBLE_UNVERIFIED = "metadata_eligible_unverified"
    DAILY_ALLOWANCE_EXHAUSTED = "daily_allowance_exhausted"
    PROVIDER_ATTEMPT_IN_FLIGHT = "provider_attempt_in_flight"


class PremiumStatusErrorCode(StrEnum):
    ACCESS_DENIED = "ACCESS_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class PremiumStatusError(Exception):
    def __init__(self, code: PremiumStatusErrorCode) -> None:
        self.code = code
        super().__init__("The premium provider status is unavailable.")


@dataclass(frozen=True, slots=True, kw_only=True)
class PremiumProviderConfiguration:
    outbound_enabled: bool = False
    alpha_vantage_credential_port_configured: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.outbound_enabled) is not bool
            or type(self.alpha_vantage_credential_port_configured) is not bool
        ):
            raise ValueError("Trusted configuration flags must be explicit booleans.")


PROVIDER_CAPABILITIES = (
    (
        PremiumProvider.ALPHA_VANTAGE,
        (
            PremiumCapability.DAILY_ADJUSTED,
            PremiumCapability.ETF_PROFILE,
            PremiumCapability.COMPANY_OVERVIEW,
            PremiumCapability.NEWS_SENTIMENT,
        ),
    ),
    (PremiumProvider.ECB, (PremiumCapability.REFERENCE_FX,)),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PremiumCapabilityStatus:
    capability: PremiumCapability
    state: PremiumReadiness
    reason: PremiumStatusReason
    canonical_publication_supported: bool
    daily_allowance: int | None = None
    attempts_charged: int | None = None
    retry_at: datetime | None = None

    def __post_init__(self) -> None:
        if (
            type(self.capability) is not PremiumCapability
            or type(self.state) is not PremiumReadiness
            or type(self.reason) is not PremiumStatusReason
            or type(self.canonical_publication_supported) is not bool
        ):
            raise ValueError("A fixed capability readiness record is required.")
        if self.canonical_publication_supported != (
            self.capability is not PremiumCapability.ETF_PROFILE
        ):
            raise ValueError(
                "Canonical ETF publication requires missing identity/currency evidence."
            )
        expected = {
            PremiumStatusReason.OUTBOUND_DISABLED: PremiumReadiness.NOT_CONFIGURED,
            PremiumStatusReason.PROVIDER_CONFIGURATION_REQUIRED: PremiumReadiness.NOT_CONFIGURED,
            PremiumStatusReason.CREDENTIAL_CONFIGURATION_REQUIRED: PremiumReadiness.NOT_CONFIGURED,
            PremiumStatusReason.CAPABILITY_RIGHTS_REQUIRED: PremiumReadiness.BLOCKED_EXTERNAL,
            PremiumStatusReason.RESEARCH_SCOPE_REQUIRED: PremiumReadiness.BLOCKED_EXTERNAL,
            PremiumStatusReason.ACQUISITION_POLICY_REQUIRED: PremiumReadiness.BLOCKED_EXTERNAL,
            PremiumStatusReason.CANONICAL_METADATA_UNAVAILABLE: PremiumReadiness.UNAVAILABLE,
            PremiumStatusReason.METADATA_ELIGIBLE_UNVERIFIED: PremiumReadiness.READY_UNVERIFIED,
            PremiumStatusReason.DAILY_ALLOWANCE_EXHAUSTED: PremiumReadiness.DEGRADED,
            PremiumStatusReason.PROVIDER_ATTEMPT_IN_FLIGHT: PremiumReadiness.DEGRADED,
        }
        if self.state is not expected[self.reason]:
            raise ValueError("Readiness must match its fixed reason.")
        detailed = self.state in {PremiumReadiness.READY_UNVERIFIED, PremiumReadiness.DEGRADED}
        if detailed:
            maximum = 24 if self.capability is PremiumCapability.REFERENCE_FX else 25
            if (
                type(self.daily_allowance) is not int
                or not 1 <= self.daily_allowance <= maximum
                or type(self.attempts_charged) is not int
                or not 0 <= self.attempts_charged <= maximum
            ):
                raise ValueError("Current authorized bounded provider allowance is required.")
        elif any(
            x is not None for x in (self.daily_allowance, self.attempts_charged, self.retry_at)
        ):
            raise ValueError("Restricted status cannot disclose operational allowance metadata.")
        if self.state is PremiumReadiness.DEGRADED:
            if self.retry_at is None:
                raise ValueError("A bounded retry clock is required.")
            if self.reason is PremiumStatusReason.DAILY_ALLOWANCE_EXHAUSTED and (
                self.attempts_charged is None
                or self.daily_allowance is None
                or self.attempts_charged < self.daily_allowance
            ):
                raise ValueError("Quota exhaustion requires actual charged attempts.")
        elif self.retry_at is not None:
            raise ValueError("Only temporary limits carry a retry clock.")
        if self.retry_at is not None:
            object.__setattr__(self, "retry_at", require_utc(self.retry_at))


@dataclass(frozen=True, slots=True, kw_only=True)
class PremiumProviderStatus:
    provider: PremiumProvider
    capabilities: tuple[PremiumCapabilityStatus, ...]

    def __post_init__(self) -> None:
        expected = dict(PROVIDER_CAPABILITIES).get(self.provider)
        if (
            type(self.provider) is not PremiumProvider
            or type(self.capabilities) is not tuple
            or any(type(x) is not PremiumCapabilityStatus for x in self.capabilities)
            or tuple(x.capability for x in self.capabilities) != expected
        ):
            raise ValueError("The exact ordered provider capability registry is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class PremiumProviderStatusView:
    account_id: UUID
    observed_at: datetime
    providers: tuple[PremiumProviderStatus, ...]
    credential_verification: Literal["unavailable"] = "unavailable"
    live_verification: Literal["unavailable"] = "unavailable"

    def __post_init__(self) -> None:
        if (
            type(self.account_id) is not UUID
            or type(self.providers) is not tuple
            or any(type(x) is not PremiumProviderStatus for x in self.providers)
            or tuple(x.provider for x in self.providers)
            != tuple(x[0] for x in PROVIDER_CAPABILITIES)
            or self.credential_verification != "unavailable"
            or self.live_verification != "unavailable"
        ):
            raise ValueError("A bounded, explicitly unverified status envelope is required.")
        object.__setattr__(self, "observed_at", require_utc(self.observed_at))


class PremiumProviderStatusService(Protocol):
    async def get_premium_provider_status(
        self, principal: Principal, account_id: UUID
    ) -> PremiumProviderStatusView: ...
