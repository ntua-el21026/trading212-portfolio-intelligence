"""Redis-backed, non-authoritative Trading 212 rate-limit coordination."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast

from redis.asyncio import Redis
from trading212_application.ingestion import (
    FailureCategory,
    IngestionCapability,
    IngestionFailure,
    RateObservation,
)

_Sleep = Callable[[float], Awaitable[None]]
_Clock = Callable[[], datetime]


class RedisRateCoordinator:
    """Persist bounded cooldowns without storing account identifiers in Redis keys."""

    def __init__(
        self,
        client: Redis,
        *,
        clock: _Clock | None = None,
        sleep: _Sleep = asyncio.sleep,
        max_cooldown_seconds: int = 3_600,
    ) -> None:
        if isinstance(max_cooldown_seconds, bool) or not 1 <= max_cooldown_seconds <= 86_400:
            raise ValueError("rate cooldown bound must be between 1 and 86400 seconds")
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep
        self._max_cooldown_milliseconds = max_cooldown_seconds * 1_000

    @classmethod
    def from_url(cls, url: str) -> RedisRateCoordinator:
        return cls(
            Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
            )
        )

    async def before_read(
        self,
        *,
        account_id: str,
        capability: IngestionCapability,
    ) -> None:
        key = _coordination_key(account_id, capability)
        try:
            raw = cast(str | bytes | None, await self._client.get(key))
        except Exception as exc:
            raise IngestionFailure(
                FailureCategory.PERSISTENCE,
                "rate-limit coordination is unavailable",
                retryable=True,
            ) from exc
        if raw is None:
            return
        if isinstance(raw, bytes):
            raw = raw.decode("ascii", errors="strict")
        try:
            eligible_milliseconds = int(raw)
        except ValueError as exc:
            raise IngestionFailure(
                FailureCategory.PERSISTENCE,
                "rate-limit coordination state is invalid",
            ) from exc
        now_milliseconds = _epoch_milliseconds(_utc(self._clock()))
        if eligible_milliseconds > now_milliseconds:
            await self._sleep((eligible_milliseconds - now_milliseconds) / 1_000)

    async def observe(
        self,
        *,
        account_id: str,
        capability: IngestionCapability,
        observation: RateObservation | None,
    ) -> None:
        if observation is None or observation.remaining > 0:
            return
        now_milliseconds = _epoch_milliseconds(_utc(self._clock()))
        eligible_milliseconds = min(
            _epoch_milliseconds(observation.reset_at),
            now_milliseconds + self._max_cooldown_milliseconds,
        )
        ttl_milliseconds = max(eligible_milliseconds - now_milliseconds, 1_000)
        try:
            persisted = cast(
                Any,
                await self._client.set(
                    _coordination_key(account_id, capability),
                    str(eligible_milliseconds),
                    px=ttl_milliseconds,
                ),
            )
        except Exception as exc:
            raise IngestionFailure(
                FailureCategory.PERSISTENCE,
                "rate-limit coordination is unavailable",
                retryable=True,
            ) from exc
        if persisted is not True:
            raise IngestionFailure(
                FailureCategory.PERSISTENCE,
                "rate-limit coordination could not be persisted",
                retryable=True,
            )

    async def aclose(self) -> None:
        await self._client.aclose()


def _coordination_key(account_id: str, capability: IngestionCapability) -> str:
    digest = hashlib.sha256(f"{account_id}\0{capability.value}".encode()).hexdigest()
    return f"t212pi:rate:v1:{digest}"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("rate coordination clock must be timezone-aware")
    return value.astimezone(UTC)


def _epoch_milliseconds(value: datetime) -> int:
    utc_value = _utc(value)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = utc_value - epoch
    return delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000
