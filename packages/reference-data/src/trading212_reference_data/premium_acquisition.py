"""Fixed acquisition composition; authorization, quota and publication remain separate."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from trading212_domain import require_utc
from trading212_domain.errors import DomainError
from trading212_domain.serialization import canonical_json, to_primitive

from .premium_acquisition_types import (
    ADAPTER_VERSION,
    AcquireCompanyOverview,
    AcquireDailyAdjusted,
    AcquireEcbReferenceFx,
    AcquireEtfProfile,
    AcquireNewsSentiment,
    AcquisitionAttempt,
    AcquisitionAttemptPort,
    AcquisitionAuthority,
    AcquisitionCommand,
    AcquisitionCredentialPort,
    AcquisitionFailure,
    AcquisitionPermit,
    AcquisitionRejected,
    AlphaVantageCredential,
    capability,
)
from .premium_acquisition_types import (
    AcquisitionFailureCode as Code,
)
from .premium_facts import (
    AcquiredSourceBatch,
    AcquisitionProvenance,
    PremiumFacts,
    premium_facts_digest,
)
from .premium_parsing import (
    parse_company_overview,
    parse_daily_adjusted,
    parse_ecb_reference_fx,
    parse_etf_profile,
    parse_news_sentiment,
)
from .premium_transport import FixedPremiumTransport, _HttpBody, _selectors


def acquisition_request_digest(command: AcquisitionCommand, permit: AcquisitionPermit) -> str:
    """Fixed semantic request identity, explicitly excluding credentials and their references."""
    host, path, params, _ = _selectors(command, permit)
    value = {
        "schema": ADAPTER_VERSION,
        "command": to_primitive(command),
        "capability": capability(command).value,
        "provider_id": str(permit.provider_id),
        "mapping_digest": permit.mapping_digest,
        "canonical_market_mapping_id": to_primitive(permit.canonical_market_mapping_id),
        "instrument_id": to_primitive(permit.instrument_id),
        "entity_id": to_primitive(permit.entity_id),
        "price_currency": to_primitive(permit.price_currency),
        "policy_version_id": str(permit.policy_version_id),
        "policy_digest": permit.policy_digest,
        "grant_id": str(permit.grant_id),
        "grant_digest": permit.grant_digest,
        "license_version_id": permit.license.id,
        "fixed_host": host,
        "fixed_path": path,
        "selectors": params,
    }
    return hashlib.sha256(
        b"premium-acquisition-request-v1\0" + canonical_json(value).encode()
    ).hexdigest()


def _status_code(value: int) -> Code:
    if value in {401, 403}:
        return Code.AUTHENTICATION_FAILED
    if value == 429:
        return Code.RATE_LIMITED
    if value in {408, 425} or 500 <= value <= 599:
        return Code.TRANSIENT_FAILURE
    return Code.PERMANENT_FAILURE


class ConfiguredPremiumAcquisition:
    def __init__(
        self,
        *,
        enabled: bool = False,
        authority: AcquisitionAuthority | None = None,
        attempts: AcquisitionAttemptPort | None = None,
        credentials: AcquisitionCredentialPort | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(enabled) is not bool:
            raise AcquisitionRejected()
        self._enabled, self._authority, self._attempts, self._credentials = (
            enabled,
            authority,
            attempts,
            credentials,
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._transport = FixedPremiumTransport()

    async def acquire_daily_adjusted(
        self, command: AcquireDailyAdjusted
    ) -> AcquiredSourceBatch | AcquisitionFailure:
        if type(command) is not AcquireDailyAdjusted:
            raise AcquisitionRejected()
        return await self._acquire(command)

    async def acquire_etf_profile(
        self, command: AcquireEtfProfile
    ) -> AcquiredSourceBatch | AcquisitionFailure:
        if type(command) is not AcquireEtfProfile:
            raise AcquisitionRejected()
        return await self._acquire(command)

    async def acquire_company_overview(
        self, command: AcquireCompanyOverview
    ) -> AcquiredSourceBatch | AcquisitionFailure:
        if type(command) is not AcquireCompanyOverview:
            raise AcquisitionRejected()
        return await self._acquire(command)

    async def acquire_news_sentiment(
        self, command: AcquireNewsSentiment
    ) -> AcquiredSourceBatch | AcquisitionFailure:
        if type(command) is not AcquireNewsSentiment:
            raise AcquisitionRejected()
        return await self._acquire(command)

    async def acquire_ecb_reference_fx(
        self, command: AcquireEcbReferenceFx
    ) -> AcquiredSourceBatch | AcquisitionFailure:
        if type(command) is not AcquireEcbReferenceFx:
            raise AcquisitionRejected()
        return await self._acquire(command)

    async def _current(self, command: AcquisitionCommand, permit: AcquisitionPermit) -> bool:
        now = require_utc(self._clock())
        return (
            self._authority is not None
            and permit.permits(command, now)
            and await self._authority.recheck(command, permit, now=now) is True
        )

    def _live_attempt(self, attempt: AcquisitionAttempt) -> bool:
        now = require_utc(self._clock())
        return attempt.reserved_at <= now < min(attempt.deadline, attempt.lease_expires_at)

    async def _acquire(
        self, command: AcquisitionCommand
    ) -> AcquiredSourceBatch | AcquisitionFailure:
        kind = capability(command)

        def fail(
            code: Code, attempt: AcquisitionAttempt | None = None, retry: datetime | None = None
        ) -> AcquisitionFailure:
            return AcquisitionFailure(
                code=code,
                capability=kind,
                request_id=command.request_id,
                attempt_id=None if attempt is None else attempt.id,
                retry_at=retry,
            )

        if not self._enabled or self._authority is None or self._attempts is None:
            return fail(Code.NOT_CONFIGURED)
        if type(command) is not AcquireEcbReferenceFx and self._credentials is None:
            return fail(Code.NOT_CONFIGURED)
        attempt: AcquisitionAttempt | None = None
        batch: AcquiredSourceBatch | None = None
        error: Code | None = None
        retry_seconds: int | None = None
        permit: AcquisitionPermit | None = None
        try:
            async with asyncio.timeout(20):
                now = require_utc(self._clock())
                permit = await self._authority.resolve(command, now=now)
                if type(permit) is not AcquisitionPermit or not permit.permits(command, now):
                    return fail(Code.ACCESS_DENIED)
                if type(command) is AcquireNewsSentiment and command.time_to > now:
                    return fail(Code.INVALID_SCHEMA)
                digest = acquisition_request_digest(command, permit)
                attempt = await self._attempts.reserve(
                    command, permit, request_digest=digest, now=require_utc(self._clock())
                )
                if attempt is None:
                    return fail(Code.RATE_LIMITED)
                if type(attempt) is not AcquisitionAttempt or (
                    attempt.request_id,
                    attempt.owner_id,
                    attempt.provider_id,
                    attempt.request_digest,
                ) != (command.request_id, command.owner_id, permit.provider_id, digest):
                    return fail(Code.ATTEMPT_FENCE_LOST)
                remaining = (
                    min(attempt.deadline, attempt.lease_expires_at) - require_utc(self._clock())
                ).total_seconds()
                if remaining <= 0:
                    return fail(Code.ATTEMPT_FENCE_LOST, attempt)
                async with asyncio.timeout(remaining):
                    try:
                        if not await self._current(command, permit):
                            raise AcquisitionRejected(Code.ACCESS_DENIED)
                        credential = None
                        if type(command) is not AcquireEcbReferenceFx:
                            assert (
                                self._credentials is not None
                                and permit.credential_reference is not None
                            )
                            credential = await self._credentials.resolve_alpha_vantage_credential(
                                permit.owner_id, permit.provider_id, permit.credential_reference
                            )
                            if type(credential) is not AlphaVantageCredential:
                                raise AcquisitionRejected(Code.AUTHENTICATION_FAILED)
                        if not await self._current(command, permit):
                            raise AcquisitionRejected(Code.ACCESS_DENIED)
                        if not self._live_attempt(attempt):
                            raise AcquisitionRejected(Code.ATTEMPT_FENCE_LOST)
                        response = await self._transfer(command, permit, credential)
                        retry_seconds = response.retry_after_seconds
                        if response.status != 200:
                            raise AcquisitionRejected(_status_code(response.status))
                        observed = require_utc(self._clock())
                        if not self._live_attempt(attempt):
                            raise AcquisitionRejected(Code.ATTEMPT_FENCE_LOST)
                        if not await self._current(command, permit):
                            raise AcquisitionRejected(Code.ACCESS_DENIED)
                        if credential is not None and credential.reveal().encode() in response.body:
                            raise AcquisitionRejected(Code.INVALID_SCHEMA)
                        facts = self._normalize(command, permit, response.body, observed)
                        if credential is not None and credential.reveal() in canonical_json(
                            to_primitive(facts)
                        ):
                            raise AcquisitionRejected(Code.INVALID_SCHEMA)
                        content_digest = premium_facts_digest(facts)
                        assert permit.license.retention_days is not None
                        expiry = min(
                            permit.expires_at,
                            observed + timedelta(days=min(30, permit.license.retention_days)),
                        )
                        if expiry <= observed or not await self._current(command, permit):
                            raise AcquisitionRejected(Code.ACCESS_DENIED)
                        batch = AcquiredSourceBatch(
                            command=command,
                            facts=facts,
                            provenance=AcquisitionProvenance(
                                owner_id=permit.owner_id,
                                account_id=permit.account_id,
                                provider_id=permit.provider_id,
                                instrument_id=permit.instrument_id,
                                entity_id=permit.entity_id,
                                canonical_market_mapping_id=permit.canonical_market_mapping_id,
                                capability=kind,
                                mapping_version_id=permit.mapping_version_id,
                                mapping_digest=permit.mapping_digest,
                                policy_version_id=permit.policy_version_id,
                                policy_digest=permit.policy_digest,
                                grant_id=permit.grant_id,
                                grant_digest=permit.grant_digest,
                                license=permit.license,
                                request_id=command.request_id,
                                request_digest=digest,
                                attempt_id=attempt.id,
                                adapter_version=ADAPTER_VERSION,
                                observed_at=observed,
                                first_known_at=observed,
                                expires_at=expiry,
                                content_digest=content_digest,
                            ),
                        )
                    except AcquisitionRejected as rejected:
                        error = rejected.code
                    except (DomainError, ValueError, UnicodeError, RecursionError):
                        error = Code.INVALID_SCHEMA
                    except TimeoutError:
                        error = Code.TIMEOUT
                    except Exception:
                        error = Code.TRANSIENT_FAILURE
                    now = require_utc(self._clock())
                    retry = None
                    if (
                        error in {Code.RATE_LIMITED, Code.TIMEOUT, Code.TRANSIENT_FAILURE}
                        and attempt.ordinal < 3
                    ):
                        delay = retry_seconds if retry_seconds is not None else attempt.ordinal
                        candidate = now + timedelta(seconds=max(attempt.ordinal, delay))
                        if candidate < attempt.deadline:
                            retry = candidate
                    if not self._live_attempt(attempt):
                        return fail(Code.ATTEMPT_FENCE_LOST, attempt)
                    if not await self._attempts.finish(
                        attempt, outcome=error, observed_at=now, retry_at=retry
                    ):
                        return fail(Code.ATTEMPT_FENCE_LOST, attempt)
                    if error is not None:
                        return fail(error, attempt, retry)
                    if not self._live_attempt(attempt):
                        return fail(Code.ATTEMPT_FENCE_LOST, attempt)
                    if batch is None or not await self._current(command, permit):
                        return fail(Code.ACCESS_DENIED, attempt)
                    if not self._live_attempt(attempt):
                        return fail(Code.ATTEMPT_FENCE_LOST, attempt)
                    return batch
        except asyncio.CancelledError:
            # No in-memory uncharging or detached completion. The durable attempt
            # lease expires; its consumed allowance and original deadline remain.
            raise
        except TimeoutError:
            error = Code.TIMEOUT
        except AcquisitionRejected as rejected:
            error = rejected.code
        except Exception:
            error = Code.TRANSIENT_FAILURE
        # A lost/expired lease never publishes a payload. The durable store owns
        # recovery; no retry is promised unless it was atomically recorded above.
        return fail(error or Code.PERMANENT_FAILURE, attempt)

    async def _transfer(
        self,
        command: AcquisitionCommand,
        permit: AcquisitionPermit,
        credential: AlphaVantageCredential | None,
    ) -> _HttpBody:
        now = require_utc(self._clock())
        if type(command) is AcquireEcbReferenceFx:
            return await self._transport.ecb_reference_fx(command, permit, now=now)
        if credential is None:
            raise AcquisitionRejected(Code.AUTHENTICATION_FAILED)
        if type(command) is AcquireDailyAdjusted:
            return await self._transport.daily_adjusted(command, permit, credential, now=now)
        if type(command) is AcquireEtfProfile:
            return await self._transport.etf_profile(command, permit, credential, now=now)
        if type(command) is AcquireCompanyOverview:
            return await self._transport.company_overview(command, permit, credential, now=now)
        if type(command) is AcquireNewsSentiment:
            return await self._transport.news_sentiment(command, permit, credential, now=now)
        raise AcquisitionRejected()

    @staticmethod
    def _normalize(
        command: AcquisitionCommand, permit: AcquisitionPermit, body: bytes, observed_at: datetime
    ) -> PremiumFacts:
        if type(command) is AcquireDailyAdjusted:
            return parse_daily_adjusted(body, command, permit, observed_at)
        if type(command) is AcquireEtfProfile:
            return parse_etf_profile(body, permit, observed_at)
        if type(command) is AcquireCompanyOverview:
            return parse_company_overview(body, permit, observed_at)
        if type(command) is AcquireNewsSentiment:
            return parse_news_sentiment(body, command, permit, observed_at)
        if type(command) is AcquireEcbReferenceFx:
            return parse_ecb_reference_fx(body, observed_at)
        raise AcquisitionRejected()
