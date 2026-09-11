"""Owner/source ordered transactions and fixed, sanitized alert failures."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import alerts as app
from trading212_domain.alert_serialization import decode_alert_rule_definition
from trading212_domain.alerts import AlertRuleVersion
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError, Principal

from .alert_authorization import AlertAuthorization, authorize_alert_request
from .alert_models import AlertCommandModel, AlertRuleModel, AlertRuleVersionModel
from .models import AuditEventModel
from .report_base import report_owner_lock

KEY = re.compile(r"^[A-Za-z0-9._:-]{1,180}$")
ACTOR = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "expired"})
AlertCaptureFactory = Callable[[Session, AlertAuthorization], app.AlertCapturePort]


def alert_owner_lock(session: Session, owner_id: UUID, *, wait: bool = True) -> bool:
    # Licensed family stores and purge share this first lock; the rule row follows it.
    return report_owner_lock(session, owner_id, wait=wait)


def fail(code: app.AlertServiceErrorCode) -> None:
    raise app.AlertServiceError(code)


def audit_alert(
    session: Session,
    authorization: AlertAuthorization,
    *,
    action: str,
    resource_id: UUID,
    at: datetime,
    reason: str | None = None,
) -> None:
    session.add(
        AuditEventModel(
            id=uuid4(),
            owner_id=authorization.owner_id,
            principal_id=authorization.principal_id,
            broker_account_id=authorization.account_id,
            action=action,
            resource_type="alert",
            resource_id=str(resource_id),
            outcome="succeeded",
            occurred_at=at,
            safe_metadata={"reason": reason} if reason else None,
        )
    )


def rule_version(row: AlertRuleVersionModel) -> AlertRuleVersion:
    payload = row.definition_payload
    if hashlib.sha256(payload).hexdigest() != row.content_digest:
        fail(app.AlertServiceErrorCode.ALERTS_UNAVAILABLE)
    return AlertRuleVersion(
        id=row.id,
        rule_id=row.rule_id,
        owner_id=row.owner_id,
        account_id=row.account_id,
        version_number=row.version_number,
        created_at=row.created_at,
        content_digest=row.content_digest,
        definition=decode_alert_rule_definition(payload),
    )


class AlertStore:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        capture_factory: AlertCaptureFactory | None = None,
        cursor_ttl_seconds: int = 3600,
        max_active_collection_snapshots_per_owner: int = 64,
        max_active_collection_members_per_owner: int = 250000,
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cursor_signing_key = cursor_signing_key
        self._capture_factory = capture_factory
        self._cursor_ttl_seconds = cursor_ttl_seconds
        self._max_collections = max_active_collection_snapshots_per_owner
        self._max_members = max_active_collection_members_per_owner

    def _now(self) -> datetime:
        return require_utc(self._clock())

    async def _run[T](self, operation: Callable[[], T]) -> T:
        def execute() -> T:
            try:
                return operation()
            except AuthorizationError:
                raise app.AlertServiceError(app.AlertServiceErrorCode.ACCESS_DENIED) from None
            except DomainError as error:
                code = (
                    app.AlertServiceErrorCode.INPUT_BOUND_EXCEEDED
                    if error.code is ErrorCode.INPUT_BOUND_EXCEEDED
                    else app.AlertServiceErrorCode.VALIDATION_FAILED
                )
                raise app.AlertServiceError(code) from None
            except SQLAlchemyError:
                raise app.AlertServiceError(
                    app.AlertServiceErrorCode.ALERTS_UNAVAILABLE, retryable=True
                ) from None

        return await asyncio.to_thread(execute)

    def _capture(self, session: Session, authorization: AlertAuthorization) -> app.AlertCapturePort:
        if self._capture_factory is not None:
            return self._capture_factory(session, authorization)
        from .alert_capture import CanonicalAlertCapture

        return CanonicalAlertCapture(
            session,
            authorization,
            now=self._now(),
            cursor_signing_key=self._cursor_signing_key,
            sessions=self._sessions,
        )

    def _references(
        self, session: Session, authorization: AlertAuthorization, definition: object
    ) -> None:
        from trading212_domain.alerts import AlertRuleDefinition

        from .alert_capture import validate_alert_references

        if not isinstance(definition, AlertRuleDefinition):
            fail(app.AlertServiceErrorCode.VALIDATION_FAILED)
        assert isinstance(definition, AlertRuleDefinition)
        validate_alert_references(session, authorization, definition, now=self._now())

    def _rule(
        self, session: Session, principal: Principal, rule_id: UUID, *, write: bool = False
    ) -> tuple[AlertRuleModel, AlertAuthorization]:
        owner = UUID(principal.owner_id)
        alert_owner_lock(session, owner)
        row = session.scalar(
            select(AlertRuleModel)
            .where(AlertRuleModel.id == rule_id, AlertRuleModel.owner_id == owner)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            fail(app.AlertServiceErrorCode.NOT_FOUND)
        assert row is not None
        authorization = authorize_alert_request(
            session, principal, account_id=row.account_id, write=write, now=self._now()
        )
        return row, authorization

    def _version(
        self, session: Session, rule: AlertRuleModel, version_id: UUID | None = None
    ) -> AlertRuleVersionModel:
        row = session.scalar(
            select(AlertRuleVersionModel).where(
                AlertRuleVersionModel.id == (version_id or rule.latest_version_id),
                AlertRuleVersionModel.owner_id == rule.owner_id,
                AlertRuleVersionModel.rule_id == rule.id,
                AlertRuleVersionModel.account_id == rule.account_id,
            )
        )
        if row is None:
            fail(app.AlertServiceErrorCode.NOT_FOUND)
        assert row is not None
        return row

    def _command(
        self,
        session: Session,
        authorization: AlertAuthorization,
        *,
        command: str,
        idempotency_key: str,
        digest: str,
    ) -> AlertCommandModel | None:
        if not KEY.fullmatch(idempotency_key):
            fail(app.AlertServiceErrorCode.VALIDATION_FAILED)
        row = session.scalar(
            select(AlertCommandModel).where(
                AlertCommandModel.owner_id == authorization.owner_id,
                AlertCommandModel.command == command,
                AlertCommandModel.idempotency_key == idempotency_key,
            )
        )
        if row is not None and (
            row.command_digest != digest or row.account_id != authorization.account_id
        ):
            fail(app.AlertServiceErrorCode.IDEMPOTENCY_KEY_REUSED)
        return row

    def _record_command(
        self,
        session: Session,
        authorization: AlertAuthorization,
        *,
        command: str,
        key: str,
        digest: str,
        result_id: UUID,
        revision: int,
        rule_id: UUID | None = None,
        event_id: UUID | None = None,
    ) -> AlertCommandModel:
        row = AlertCommandModel(
            id=uuid4(),
            owner_id=authorization.owner_id,
            account_id=authorization.account_id,
            created_at=self._now(),
            command=command,
            idempotency_key=key,
            command_digest=digest,
            result_id=result_id,
            resulting_revision=revision,
            rule_id=rule_id,
            event_id=event_id,
        )
        session.add(row)
        return row

    @staticmethod
    def _revision(actual: int, expected: int) -> None:
        if type(expected) is not int or expected < 1:
            fail(app.AlertServiceErrorCode.REVISION_REQUIRED)
        if actual != expected:
            fail(app.AlertServiceErrorCode.REVISION_MISMATCH)
