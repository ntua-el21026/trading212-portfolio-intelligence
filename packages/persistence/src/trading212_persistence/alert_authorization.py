"""Current persisted alert authority using the established principal/grant checks."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session
from trading212_application.alerts import alert_required_scopes
from trading212_domain.alerts import AlertRuleDefinition
from trading212_security.principals import Principal, Scope

from .report_authorization import (
    ReportAuthorization as AlertAuthorization,
)
from .report_authorization import (
    authorize_report_job,
    authorize_report_request,
)


def authorize_alert_request(
    session: Session,
    principal: Principal,
    *,
    account_id: UUID,
    now: datetime,
    write: bool = False,
    definition: AlertRuleDefinition | None = None,
) -> AlertAuthorization:
    scopes = alert_required_scopes(definition, write=write)
    return authorize_report_request(
        session, principal, account_id=account_id, required_scopes=scopes, now=now
    )


def authorize_alert_job(
    session: Session,
    *,
    principal_id: UUID,
    owner_id: UUID,
    account_id: UUID,
    definition: AlertRuleDefinition,
    expires_at: datetime,
    now: datetime,
) -> AlertAuthorization:
    return authorize_report_job(
        session,
        principal_id=principal_id,
        owner_id=owner_id,
        account_id=account_id,
        required_scopes=alert_required_scopes(definition, write=True),
        expires_at=expires_at,
        now=now,
    )


__all__ = [
    "ALERT_READ_SCOPES",
    "AlertAuthorization",
    "authorize_alert_job",
    "authorize_alert_request",
]

ALERT_READ_SCOPES = frozenset({Scope.PORTFOLIO_READ, Scope.ALERTS_READ})
