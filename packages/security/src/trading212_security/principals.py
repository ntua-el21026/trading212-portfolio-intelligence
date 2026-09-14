"""Authentication principals and owner/account authorization policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from .identity import is_string_or_uri


class Scope(StrEnum):
    PORTFOLIO_READ = "portfolio:read"
    ACTIVITY_READ = "activity:read"
    PORTFOLIO_REFRESH = "portfolio:refresh"
    CONFIGURATION_READ = "configuration:read"
    TARGETS_READ = "targets:read"
    TARGETS_WRITE = "targets:write"
    ANALYTICS_READ = "analytics:read"
    PLANS_WRITE = "plans:write"
    REPORTS_READ = "reports:read"
    REPORTS_WRITE = "reports:write"
    ALERTS_READ = "alerts:read"
    ALERTS_WRITE = "alerts:write"
    RISK_WRITE = "risk:write"
    SCENARIOS_WRITE = "scenarios:write"
    PROJECTIONS_WRITE = "projections:write"
    GOALS_WRITE = "goals:write"
    RESEARCH_READ = "research:read"
    RESEARCH_WRITE = "research:write"
    PREFERENCES_READ = "preferences:read"
    PREFERENCES_WRITE = "preferences:write"
    AGGREGATE_READ = "aggregate:read"
    AGGREGATE_WRITE = "aggregate:write"


class AuthenticationError(RuntimeError):
    pass


class AuthorizationError(RuntimeError):
    """Intentionally does not reveal whether a private resource exists."""


_OPAQUE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: str
    owner_id: str
    issuer: str
    subject: str
    scopes: frozenset[Scope]
    authenticated_at: datetime
    expires_at: datetime
    session_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("principal_id", "owner_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _OPAQUE_ID.fullmatch(value):
                raise AuthenticationError(f"invalid {name}")
        for name in ("issuer", "subject"):
            if not is_string_or_uri(getattr(self, name)):
                raise AuthenticationError(f"invalid {name}")
        for name in ("authenticated_at", "expires_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise AuthenticationError(f"{name} must be timezone-aware")
            object.__setattr__(self, name, value.astimezone(UTC))
        if self.expires_at <= self.authenticated_at:
            raise AuthenticationError("principal expiry must follow authentication")
        if not self.scopes or not all(isinstance(scope, Scope) for scope in self.scopes):
            raise AuthenticationError("principal must contain known scopes")


class AccountOwnership(Protocol):
    async def owner_for_account(self, account_id: str) -> str | None: ...


class Authorizer:
    def require_scope(self, principal: Principal, scope: Scope, *, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("authorization clock must be timezone-aware")
        if principal.expires_at <= now.astimezone(UTC) or scope not in principal.scopes:
            raise AuthorizationError("access denied")

    def require_owner(self, principal: Principal, owner_id: str) -> None:
        if principal.owner_id != owner_id:
            raise AuthorizationError("access denied")

    async def require_account(
        self,
        principal: Principal,
        account_id: str,
        ownership: AccountOwnership,
    ) -> None:
        owner_id = await ownership.owner_for_account(account_id)
        if owner_id is None or owner_id != principal.owner_id:
            raise AuthorizationError("access denied")
