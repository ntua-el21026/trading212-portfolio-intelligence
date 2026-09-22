"""Fixed, explicitly unverified readiness; no confidential metadata in blocked states."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from trading212_api_contracts.premium_providers import PremiumCapabilityStatus
from trading212_application import premium_provider_status as app
from trading212_domain.serialization import to_primitive
from trading212_persistence.premium_provider_status import _capability

AT = datetime(2026, 9, 15, 23, 59, 59, tzinfo=UTC)


def row(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "provider_key": "alpha_vantage",
        "capability": "daily_adjusted",
        "provider_configured": True,
        "research_allowed": True,
        "rights_allowed": True,
        "policy_enabled": True,
        "metadata_ready": True,
        "daily_allowance": 25,
        "attempts_charged": 0,
        "inflight_until": None,
    }
    value.update(changes)
    return value


@pytest.mark.parametrize("enabled", [False, True])
def test_absent_credential_port_is_not_configured_even_with_valid_grants(enabled: bool) -> None:
    value = _capability(row(), app.PremiumProviderConfiguration(outbound_enabled=enabled), AT)
    assert value.state is app.PremiumReadiness.NOT_CONFIGURED
    assert value.reason is app.PremiumStatusReason.CREDENTIAL_CONFIGURATION_REQUIRED
    assert value.daily_allowance is None
    assert value.attempts_charged is None
    assert value.retry_at is None


def test_present_credential_port_never_claims_verified_live() -> None:
    value = _capability(
        row(),
        app.PremiumProviderConfiguration(
            outbound_enabled=True, alpha_vantage_credential_port_configured=True
        ),
        AT,
    )
    assert value.state is app.PremiumReadiness.READY_UNVERIFIED
    wire = PremiumCapabilityStatus.model_validate(to_primitive(value)).model_dump()
    wire["state"] = "verified_live"
    with pytest.raises(ValueError):
        PremiumCapabilityStatus.model_validate(wire)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"research_allowed": False}, app.PremiumStatusReason.RESEARCH_SCOPE_REQUIRED),
        ({"rights_allowed": False}, app.PremiumStatusReason.CAPABILITY_RIGHTS_REQUIRED),
        ({"policy_enabled": False}, app.PremiumStatusReason.ACQUISITION_POLICY_REQUIRED),
        ({"metadata_ready": False}, app.PremiumStatusReason.CANONICAL_METADATA_UNAVAILABLE),
    ],
)
def test_restricted_status_withholds_allowance(
    change: dict[str, object], reason: app.PremiumStatusReason
) -> None:
    value = _capability(
        row(**change),
        app.PremiumProviderConfiguration(
            outbound_enabled=True, alpha_vantage_credential_port_configured=True
        ),
        AT,
    )
    assert value.reason is reason and value.daily_allowance is value.attempts_charged is None
    with pytest.raises(ValueError):
        replace(value, daily_allowance=25, attempts_charged=0)


def test_quota_retry_is_actual_next_utc_day_and_ecb_needs_no_credential() -> None:
    value = _capability(
        row(provider_key="ecb", capability="reference_fx", daily_allowance=24, attempts_charged=24),
        app.PremiumProviderConfiguration(outbound_enabled=True),
        AT,
    )
    assert value.reason is app.PremiumStatusReason.DAILY_ALLOWANCE_EXHAUSTED
    assert value.retry_at == datetime(2026, 9, 16, tzinfo=UTC)
    with pytest.raises(ValueError):
        replace(value, attempts_charged=23)
    with pytest.raises(ValueError):
        replace(value, state=app.PremiumReadiness.READY_UNVERIFIED)


def test_inflight_is_a_fixed_temporary_reason_and_etf_has_no_canonical_publication() -> None:
    value = _capability(
        row(capability="etf_profile", inflight_until=AT + timedelta(seconds=5)),
        app.PremiumProviderConfiguration(
            outbound_enabled=True, alpha_vantage_credential_port_configured=True
        ),
        AT,
    )
    assert (
        value.state is app.PremiumReadiness.DEGRADED and not value.canonical_publication_supported
    )
    assert value.retry_at == AT + timedelta(seconds=5)
    with pytest.raises(ValueError):
        replace(value, retry_at=None)
