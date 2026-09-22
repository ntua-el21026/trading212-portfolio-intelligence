import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from trading212_reference_data import premium_acquisition as module
from trading212_reference_data.premium_acquisition import (
    ConfiguredPremiumAcquisition,
    acquisition_request_digest,
)
from trading212_reference_data.premium_acquisition_types import (
    AcquireDailyAdjusted,
    AcquisitionAttempt,
    AcquisitionCommand,
    AcquisitionFailure,
    AcquisitionPermit,
    AlphaVantageCredential,
)
from trading212_reference_data.premium_acquisition_types import (
    AcquisitionFailureCode as Code,
)
from trading212_reference_data.premium_facts import AcquiredSourceBatch
from trading212_reference_data.premium_transport import FixedPremiumTransport, _HttpBody

from tests.unit.reference_data.premium_fixtures import AT, SECRET, command, daily, encoded, permit


class Authority:
    def __init__(self, value: AcquisitionPermit) -> None:
        self.value, self.checks = value, 0
        self.deny_at: int | None = None

    async def resolve(
        self, command: AcquisitionCommand, *, now: datetime
    ) -> AcquisitionPermit | None:
        return self.value

    async def recheck(
        self, command: AcquisitionCommand, permit: AcquisitionPermit, *, now: datetime
    ) -> bool:
        self.checks += 1
        return self.checks != self.deny_at


class Credentials:
    def __init__(self) -> None:
        self.calls = 0
        self.missing = False

    async def resolve_alpha_vantage_credential(
        self, owner_id: UUID, provider_id: UUID, reference: str
    ) -> AlphaVantageCredential | None:
        self.calls += 1
        return None if self.missing else AlphaVantageCredential(SECRET)


class Attempts:
    def __init__(self) -> None:
        self.ordinal = 1
        self.denied = False
        self.foreign = False
        self.finish_allowed = True
        self.reservations: list[str] = []
        self.finished: list[tuple[Code | None, datetime | None]] = []

    async def reserve(
        self,
        command: AcquisitionCommand,
        permit: AcquisitionPermit,
        *,
        request_digest: str,
        now: datetime,
    ) -> AcquisitionAttempt | None:
        self.reservations.append(request_digest)
        if self.denied:
            return None
        return AcquisitionAttempt(
            id=UUID(int=99),
            request_id=command.request_id,
            owner_id=command.owner_id,
            provider_id=permit.provider_id,
            request_digest="f" * 64 if self.foreign else request_digest,
            ordinal=self.ordinal,
            first_started_at=AT,
            reserved_at=now,
            deadline=AT + timedelta(seconds=20),
            lease_expires_at=AT + timedelta(seconds=20),
        )

    async def finish(
        self,
        attempt: AcquisitionAttempt,
        *,
        outcome: Code | None,
        observed_at: datetime,
        retry_at: datetime | None,
    ) -> bool:
        self.finished.append((outcome, retry_at))
        return self.finish_allowed


class Transport(FixedPremiumTransport):
    def __init__(self) -> None:
        self.calls = 0
        self.status = 200
        self.retry: int | None = None
        self.error: Exception | None = None
        self.payload: bytes | None = None

    async def _request(
        self,
        command: AcquisitionCommand,
        permit: AcquisitionPermit,
        credential: AlphaVantageCredential | None,
        *,
        now: datetime,
    ) -> _HttpBody:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return _HttpBody(
            self.status, encoded(daily()) if self.payload is None else self.payload, self.retry
        )


def setup() -> tuple[
    ConfiguredPremiumAcquisition, AcquireDailyAdjusted, Authority, Credentials, Attempts, Transport
]:
    request = command()
    assert isinstance(request, AcquireDailyAdjusted)
    auth, credentials, attempts, transport = (
        Authority(permit(request)),
        Credentials(),
        Attempts(),
        Transport(),
    )
    adapter = ConfiguredPremiumAcquisition(
        enabled=True, authority=auth, attempts=attempts, credentials=credentials, clock=lambda: AT
    )
    adapter._transport = transport
    return adapter, request, auth, credentials, attempts, transport


@pytest.mark.asyncio
async def test_default_and_missing_ports_do_not_resolve_secret_or_dispatch() -> None:
    _adapter, request, auth, credentials, attempts, transport = setup()
    assert isinstance(
        await ConfiguredPremiumAcquisition().acquire_daily_adjusted(request), AcquisitionFailure
    )
    missing = ConfiguredPremiumAcquisition(
        enabled=True, authority=auth, attempts=attempts, clock=lambda: AT
    )
    result = await missing.acquire_daily_adjusted(request)
    assert isinstance(result, AcquisitionFailure) and result.code is Code.NOT_CONFIGURED
    assert credentials.calls == transport.calls == 0 and attempts.reservations == []


@pytest.mark.asyncio
async def test_exact_normalization_requires_reserved_fenced_attempt_and_current_rights() -> None:
    adapter, request, auth, credentials, attempts, transport = setup()
    result = await adapter.acquire_daily_adjusted(request)
    assert isinstance(result, AcquiredSourceBatch)
    assert credentials.calls == transport.calls == 1 and auth.checks >= 4
    assert attempts.reservations == [acquisition_request_digest(request, auth.value)]
    assert attempts.finished == [(None, None)]
    assert result.provenance.first_known_at == result.provenance.observed_at == AT
    assert result.provenance.expires_at == auth.value.expires_at
    assert result.provenance.grant_id == auth.value.grant_id
    assert SECRET not in repr(result) and "apikey" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("denied,foreign", [(True, False), (False, True)])
async def test_quota_or_foreign_attempt_receipt_denies_before_credentials(
    denied: bool, foreign: bool
) -> None:
    adapter, request, _, credentials, attempts, transport = setup()
    attempts.denied, attempts.foreign = denied, foreign
    result = await adapter.acquire_daily_adjusted(request)
    assert isinstance(result, AcquisitionFailure)
    assert result.code is (Code.RATE_LIMITED if denied else Code.ATTEMPT_FENCE_LOST)
    assert credentials.calls == transport.calls == 0 and not attempts.finished


@pytest.mark.asyncio
async def test_current_revocation_precedes_private_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, request, auth, _, attempts, transport = setup()
    auth.deny_at = 3  # Body receipt, before private normalization.

    def forbidden(*args: object) -> None:
        raise AssertionError("provider decoder must not run")

    monkeypatch.setattr(module, "parse_daily_adjusted", forbidden)
    result = await adapter.acquire_daily_adjusted(request)
    assert isinstance(result, AcquisitionFailure) and result.code is Code.ACCESS_DENIED
    assert transport.calls == 1 and attempts.finished == [(Code.ACCESS_DENIED, None)]


@pytest.mark.asyncio
async def test_final_revocation_or_failed_attempt_finish_never_publishes() -> None:
    for revoked in (True, False):
        adapter, request, auth, _, attempts, _ = setup()
        if revoked:
            auth.deny_at = 5
        else:
            attempts.finish_allowed = False
        result = await adapter.acquire_daily_adjusted(request)
        assert isinstance(result, AcquisitionFailure)
        assert result.code is (Code.ACCESS_DENIED if revoked else Code.ATTEMPT_FENCE_LOST)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ordinal,delay,expected",
    [(1, None, 1), (2, None, 2), (1, 12, 12), (1, 60, None), (3, None, None)],
)
async def test_retry_is_durable_scheduled_and_original_deadline_wins(
    monkeypatch: pytest.MonkeyPatch, ordinal: int, delay: int | None, expected: int | None
) -> None:
    adapter, request, _, _, attempts, transport = setup()
    attempts.ordinal, transport.status, transport.retry = ordinal, 429, delay

    async def no_sleep(*args: object, **kwargs: object) -> None:
        raise AssertionError("the worker must not sleep for a retry")

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    result = await adapter.acquire_daily_adjusted(request)
    assert isinstance(result, AcquisitionFailure) and result.code is Code.RATE_LIMITED
    retry = None if expected is None else AT + timedelta(seconds=expected)
    assert result.retry_at == retry and attempts.finished == [(Code.RATE_LIMITED, retry)]
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_missing_credential_and_raw_exception_are_sanitized() -> None:
    adapter, request, _, credentials, attempts, transport = setup()
    credentials.missing = True
    result = await adapter.acquire_daily_adjusted(request)
    assert isinstance(result, AcquisitionFailure) and result.code is Code.AUTHENTICATION_FAILED
    assert transport.calls == 0 and attempts.finished == [(Code.AUTHENTICATION_FAILED, None)]
    credentials.missing = False
    transport.error = RuntimeError(f"raw URL ?apikey={SECRET} provider body")
    result = await adapter.acquire_daily_adjusted(request)
    assert isinstance(result, AcquisitionFailure) and SECRET not in repr(result)


def test_request_digest_binds_exact_window_mapping_grant_and_excludes_credentials() -> None:
    _, request, auth, _, _, _ = setup()
    original = acquisition_request_digest(request, auth.value)
    assert original != acquisition_request_digest(
        replace(request, request_id=UUID(int=100)), auth.value
    )
    assert original != acquisition_request_digest(
        request, replace(auth.value, grant_digest="d" * 64)
    )
    assert len(original) == 64 and SECRET not in original


@pytest.mark.asyncio
async def test_expired_attempt_during_finish_cannot_return_saved_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, request, _, _, attempts, _ = setup()
    clock = [AT]
    adapter._clock = lambda: clock[0]
    original = attempts.finish

    async def late(
        attempt: AcquisitionAttempt,
        *,
        outcome: Code | None,
        observed_at: datetime,
        retry_at: datetime | None,
    ) -> bool:
        result = await original(
            attempt, outcome=outcome, observed_at=observed_at, retry_at=retry_at
        )
        clock[0] += timedelta(seconds=20)
        return result

    monkeypatch.setattr(attempts, "finish", late)
    result = await adapter.acquire_daily_adjusted(request)
    assert isinstance(result, AcquisitionFailure) and result.code is Code.ATTEMPT_FENCE_LOST
    assert result.retry_at is None


@pytest.mark.asyncio
async def test_successful_body_cannot_echo_the_credential_into_retained_source_data() -> None:
    adapter, request, _, _, attempts, transport = setup()
    raw = daily()
    raw["ignored_metadata"] = SECRET
    transport.payload = encoded(raw)
    result = await adapter.acquire_daily_adjusted(request)
    assert isinstance(result, AcquisitionFailure) and result.code is Code.INVALID_SCHEMA
    assert result.retry_at is None and SECRET not in repr(result)
    assert attempts.finished == [(Code.INVALID_SCHEMA, None)]
