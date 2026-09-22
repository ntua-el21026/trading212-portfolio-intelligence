"""One exact account-scoped metadata operation; no credential or subject fields."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator

from .historical import HistoricalSchema
from .targets import AwareInstant, UUIDString

PremiumProviderKey = Literal["alpha_vantage", "ecb"]
PremiumProviderCapability = Literal[
    "daily_adjusted", "etf_profile", "company_overview", "news_sentiment", "reference_fx"
]
PremiumProviderReadiness = Literal[
    "not_configured", "blocked_external", "ready_unverified", "degraded", "unavailable"
]
PremiumProviderReason = Literal[
    "outbound_disabled",
    "provider_configuration_required",
    "credential_configuration_required",
    "capability_rights_required",
    "research_scope_required",
    "acquisition_policy_required",
    "canonical_metadata_unavailable",
    "metadata_eligible_unverified",
    "daily_allowance_exhausted",
    "provider_attempt_in_flight",
]


class PremiumCapabilityStatus(HistoricalSchema):
    capability: PremiumProviderCapability
    state: PremiumProviderReadiness
    reason: PremiumProviderReason
    canonical_publication_supported: StrictBool
    daily_allowance: Annotated[StrictInt, Field(ge=1, le=25)] | None = None
    attempts_charged: Annotated[StrictInt, Field(ge=0, le=25)] | None = None
    retry_at: AwareInstant | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.canonical_publication_supported != (self.capability != "etf_profile"):
            raise ValueError("Canonical ETF publication lacks required identity/currency evidence.")
        expected = {
            "outbound_disabled": "not_configured",
            "provider_configuration_required": "not_configured",
            "credential_configuration_required": "not_configured",
            "capability_rights_required": "blocked_external",
            "research_scope_required": "blocked_external",
            "acquisition_policy_required": "blocked_external",
            "canonical_metadata_unavailable": "unavailable",
            "metadata_eligible_unverified": "ready_unverified",
            "daily_allowance_exhausted": "degraded",
            "provider_attempt_in_flight": "degraded",
        }
        if self.state != expected[self.reason]:
            raise ValueError("Readiness must match its fixed reason.")
        detailed = self.state in {"ready_unverified", "degraded"}
        maximum = 24 if self.capability == "reference_fx" else 25
        if detailed:
            if (
                self.daily_allowance is None
                or self.attempts_charged is None
                or self.daily_allowance > maximum
                or self.attempts_charged > maximum
            ):
                raise ValueError("Current authorized allowance metadata is required.")
        elif any(
            x is not None for x in (self.daily_allowance, self.attempts_charged, self.retry_at)
        ):
            raise ValueError("Restricted status cannot expose allowance metadata.")
        if self.state == "degraded":
            if self.retry_at is None:
                raise ValueError("A bounded retry clock is required.")
            if self.reason == "daily_allowance_exhausted" and (
                self.attempts_charged is None
                or self.daily_allowance is None
                or self.attempts_charged < self.daily_allowance
            ):
                raise ValueError("Quota exhaustion requires actual charged attempts.")
        elif self.retry_at is not None:
            raise ValueError("Only temporary limits carry a retry clock.")
        return self


class PremiumProviderStatus(HistoricalSchema):
    provider: PremiumProviderKey
    capabilities: Annotated[list[PremiumCapabilityStatus], Field(min_length=1, max_length=4)]

    @model_validator(mode="after")
    def fixed_registry(self) -> Self:
        expected = {
            "alpha_vantage": (
                "daily_adjusted",
                "etf_profile",
                "company_overview",
                "news_sentiment",
            ),
            "ecb": ("reference_fx",),
        }[self.provider]
        if tuple(x.capability for x in self.capabilities) != expected:
            raise ValueError("The fixed capability registry differs.")
        return self


class PremiumProviderStatusResponse(HistoricalSchema):
    account_id: UUIDString
    observed_at: AwareInstant
    providers: Annotated[list[PremiumProviderStatus], Field(min_length=2, max_length=2)]
    credential_verification: Literal["unavailable"] = "unavailable"
    live_verification: Literal["unavailable"] = "unavailable"

    @model_validator(mode="after")
    def fixed_providers(self) -> Self:
        if (
            tuple(x.provider for x in self.providers) != ("alpha_vantage", "ecb")
            or len(self.model_dump_json().encode("utf-8")) > 16 * 1024
        ):
            raise ValueError("The bounded provider registry differs.")
        return self
