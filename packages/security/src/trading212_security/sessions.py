"""Server-side sessions, signed opaque cookies, CSRF, and revocation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .principals import AuthenticationError, Principal


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: str
    principal: Principal
    csrf_digest: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True, repr=False)
class SessionGrant:
    cookie_value: str
    csrf_token: str
    expires_at: datetime

    def __repr__(self) -> str:
        return "SessionGrant(redacted=True)"


class SessionStore(Protocol):
    async def put(self, record: SessionRecord) -> None: ...

    async def get(self, session_id: str) -> SessionRecord | None: ...

    async def revoke(self, session_id: str, *, now: datetime) -> None: ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}

    async def put(self, record: SessionRecord) -> None:
        self._records[record.id] = record

    async def get(self, session_id: str) -> SessionRecord | None:
        return self._records.get(session_id)

    async def revoke(self, session_id: str, *, now: datetime) -> None:
        record = self._records.get(session_id)
        if record is not None and record.revoked_at is None:
            self._records[session_id] = replace(record, revoked_at=now.astimezone(UTC))


class SessionManager:
    def __init__(
        self,
        *,
        store: SessionStore,
        signing_key: bytes,
        clock: Callable[[], datetime],
        ttl: timedelta = timedelta(hours=1),
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("session signing key must contain at least 256 bits")
        if ttl < timedelta(minutes=5) or ttl > timedelta(days=1):
            raise ValueError("session TTL must be between five minutes and one day")
        self._store = store
        self._signing_key = signing_key
        self._clock = clock
        self._ttl = ttl

    async def create(self, principal: Principal) -> SessionGrant:
        now = self._clock().astimezone(UTC)
        session_id = _token(32)
        csrf_token = _token(32)
        expires_at = min(now + self._ttl, principal.expires_at)
        record = SessionRecord(
            id=session_id,
            principal=principal,
            csrf_digest=_digest(csrf_token),
            created_at=now,
            expires_at=expires_at,
        )
        await self._store.put(record)
        return SessionGrant(
            cookie_value=f"{session_id}.{self._sign(session_id)}",
            csrf_token=csrf_token,
            expires_at=expires_at,
        )

    async def authenticate(self, cookie_value: str) -> Principal:
        session_id = self._verify_cookie(cookie_value)
        record = await self._store.get(session_id)
        now = self._clock().astimezone(UTC)
        if (
            record is None
            or record.revoked_at is not None
            or record.expires_at <= now
            or record.principal.expires_at <= now
        ):
            raise AuthenticationError("invalid session")
        return record.principal

    async def validate_csrf(self, cookie_value: str, csrf_token: str) -> None:
        session_id = self._verify_cookie(cookie_value)
        record = await self._store.get(session_id)
        if record is None or not csrf_token:
            raise AuthenticationError("invalid CSRF token")
        if not hmac.compare_digest(record.csrf_digest, _digest(csrf_token)):
            raise AuthenticationError("invalid CSRF token")

    async def revoke(self, cookie_value: str) -> None:
        session_id = self._verify_cookie(cookie_value)
        await self._store.revoke(session_id, now=self._clock().astimezone(UTC))

    def _verify_cookie(self, cookie_value: str) -> str:
        if not cookie_value or len(cookie_value) > 512 or cookie_value.count(".") != 1:
            raise AuthenticationError("invalid session")
        session_id, supplied = cookie_value.split(".", 1)
        if not hmac.compare_digest(supplied, self._sign(session_id)):
            raise AuthenticationError("invalid session")
        return session_id

    def _sign(self, value: str) -> str:
        signature = hmac.new(self._signing_key, value.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def _token(size: int) -> str:
    return secrets.token_urlsafe(size)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
