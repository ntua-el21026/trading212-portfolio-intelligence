"""Current durable readiness with a bounded full-request statement inventory."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import premium_provider_status as app
from trading212_domain import require_utc
from trading212_security.principals import AuthorizationError, Authorizer, Principal, Scope

from .acquisition_store import acquisition_lock
from .premium_provider_status_sql import STATUS_SQL
from .report_authorization import ReportAuthorization, authorize_report_request


def _capability(
    row: Mapping[str, Any], configuration: app.PremiumProviderConfiguration, at: datetime
) -> app.PremiumCapabilityStatus:
    capability = app.PremiumCapability(row["capability"])
    state, reason = app.PremiumReadiness, app.PremiumStatusReason
    selected_state, selected_reason = state.READY_UNVERIFIED, reason.METADATA_ELIGIBLE_UNVERIFIED
    if (
        row["provider_key"] == "alpha_vantage"
        and not configuration.alpha_vantage_credential_port_configured
    ):
        selected_state, selected_reason = (
            state.NOT_CONFIGURED,
            reason.CREDENTIAL_CONFIGURATION_REQUIRED,
        )
    elif not configuration.outbound_enabled:
        selected_state, selected_reason = state.NOT_CONFIGURED, reason.OUTBOUND_DISABLED
    elif not row["provider_configured"]:
        selected_state, selected_reason = (
            state.NOT_CONFIGURED,
            reason.PROVIDER_CONFIGURATION_REQUIRED,
        )
    elif not row["research_allowed"]:
        selected_state, selected_reason = state.BLOCKED_EXTERNAL, reason.RESEARCH_SCOPE_REQUIRED
    elif not row["rights_allowed"]:
        selected_state, selected_reason = state.BLOCKED_EXTERNAL, reason.CAPABILITY_RIGHTS_REQUIRED
    elif not row["policy_enabled"]:
        selected_state, selected_reason = state.BLOCKED_EXTERNAL, reason.ACQUISITION_POLICY_REQUIRED
    elif not row["metadata_ready"]:
        selected_state, selected_reason = state.UNAVAILABLE, reason.CANONICAL_METADATA_UNAVAILABLE
    elif row["attempts_charged"] >= row["daily_allowance"]:
        selected_state, selected_reason = state.DEGRADED, reason.DAILY_ALLOWANCE_EXHAUSTED
    elif row["inflight_until"] is not None:
        selected_state, selected_reason = state.DEGRADED, reason.PROVIDER_ATTEMPT_IN_FLIGHT
    detailed = selected_state in {state.READY_UNVERIFIED, state.DEGRADED}
    retry_at = None
    if selected_reason is reason.DAILY_ALLOWANCE_EXHAUSTED:
        retry_at = datetime.combine(at.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    elif selected_reason is reason.PROVIDER_ATTEMPT_IN_FLIGHT:
        retry_at = row["inflight_until"]
    return app.PremiumCapabilityStatus(
        capability=capability,
        state=selected_state,
        reason=selected_reason,
        canonical_publication_supported=capability is not app.PremiumCapability.ETF_PROFILE,
        daily_allowance=row["daily_allowance"] if detailed else None,
        attempts_charged=row["attempts_charged"] if detailed else None,
        retry_at=retry_at,
    )


class PostgresPremiumProviderStatusService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        configuration: app.PremiumProviderConfiguration | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._configuration = configuration or app.PremiumProviderConfiguration()
        if type(self._configuration) is not app.PremiumProviderConfiguration:
            raise ValueError("Explicit trusted provider configuration is required.")
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return require_utc(self._clock())

    def _projection(
        self, session: Session, auth: ReportAuthorization, principal: Principal, at: datetime
    ) -> app.PremiumProviderStatusView:
        rows = (
            session.execute(
                text(STATUS_SQL),
                {
                    "owner": auth.owner_id,
                    "principal": auth.principal_id,
                    "at": at,
                    "utc_day": at.date(),
                    "research_token": Scope.RESEARCH_READ in principal.scopes,
                },
            )
            .mappings()
            .all()
        )
        expected = [
            (index, provider.value, capability.value)
            for index, (provider, capability) in enumerate(
                (p, c) for p, capabilities in app.PROVIDER_CAPABILITIES for c in capabilities
            )
        ]
        if [(row["ordinal"], row["provider_key"], row["capability"]) for row in rows] != expected:
            raise app.PremiumStatusError(app.PremiumStatusErrorCode.SOURCE_UNAVAILABLE)
        capabilities = tuple(_capability(dict(row), self._configuration, at) for row in rows)
        return app.PremiumProviderStatusView(
            account_id=auth.account_id,
            observed_at=at,
            providers=(
                app.PremiumProviderStatus(
                    provider=app.PremiumProvider.ALPHA_VANTAGE, capabilities=capabilities[:4]
                ),
                app.PremiumProviderStatus(
                    provider=app.PremiumProvider.ECB, capabilities=capabilities[4:]
                ),
            ),
        )

    async def get_premium_provider_status(
        self, principal: Principal, account_id: UUID
    ) -> app.PremiumProviderStatusView:
        if type(account_id) is not UUID:
            raise app.PremiumStatusError(app.PremiumStatusErrorCode.VALIDATION_FAILED)
        try:
            for scope in app.PROVIDER_STATUS_SCOPES:
                Authorizer().require_scope(principal, scope, now=self._now())
        except AuthorizationError:
            raise app.PremiumStatusError(app.PremiumStatusErrorCode.ACCESS_DENIED) from None

        def execute() -> app.PremiumProviderStatusView:
            try:
                with self._sessions() as session, session.begin():
                    auth = authorize_report_request(
                        session,
                        principal,
                        account_id=account_id,
                        required_scopes=app.PROVIDER_STATUS_SCOPES,
                        now=self._now(),
                    )
                    acquisition_lock(session, auth.owner_id)
                    self._projection(session, auth, principal, self._now())
                    # Rebuild, rather than return an earlier eligibility snapshot.
                    # This also changes the quota day exactly at UTC midnight.
                    at = self._now()
                    result = self._projection(session, auth, principal, at)
                    auth.check(session, now=at)
                    return result
            except AuthorizationError:
                raise app.PremiumStatusError(app.PremiumStatusErrorCode.ACCESS_DENIED) from None
            except (SQLAlchemyError, ValueError):
                raise app.PremiumStatusError(
                    app.PremiumStatusErrorCode.SOURCE_UNAVAILABLE
                ) from None

        return await asyncio.to_thread(execute)
