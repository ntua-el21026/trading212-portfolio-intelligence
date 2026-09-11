"""Lifecycle replay rechecks the original version's current material grant."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from trading212_application import alerts as app
from trading212_domain import alerts as domain
from trading212_persistence.alert_authorization import authorize_alert_request
from trading212_persistence.alert_models import (
    AlertCommandModel,
    AlertEvaluationJobModel,
    AlertEvaluationModel,
    AlertEventModel,
    AlertInputSnapshotModel,
    AlertRuleEventModel,
    AlertRuleModel,
    AlertRuleVersionModel,
    InAppNotificationModel,
)
from trading212_persistence.alert_service import PostgresAlertService
from trading212_persistence.models import AuditEventModel, PrincipalModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_security.principals import Scope

from tests.integration.test_alert_postgres import KEY, AlertCase
from tests.integration.test_alert_postgres import alert_case as alert_case
from tests.integration.test_alert_postgres import alert_database as alert_database
from tests.unit.analytics.alert_factories import predicate

pytestmark = pytest.mark.integration


def _stored_state(case: AlertCase) -> tuple[object, ...]:
    """Compare actual canonical state and alert audit records, excluding grant provisioning."""
    owner = UUID(case.principal.owner_id)
    result: list[object] = []
    with case.sessions() as session:
        models = (
            AlertRuleModel,
            AlertRuleVersionModel,
            AlertRuleEventModel,
            AlertCommandModel,
            AlertEvaluationJobModel,
            AlertInputSnapshotModel,
            AlertEvaluationModel,
            AlertEventModel,
            InAppNotificationModel,
        )
        result.extend(
            tuple(
                tuple(row)
                for row in session.execute(
                    select(model.__table__).where(model.owner_id == owner).order_by(model.id)
                )
            )
            for model in models
        )
        result.append(
            tuple(
                tuple(row)
                for row in session.execute(
                    select(AuditEventModel.__table__)
                    .where(
                        AuditEventModel.owner_id == owner,
                        AuditEventModel.action.like("alert.%"),
                    )
                    .order_by(AuditEventModel.id)
                )
            )
        )
    return tuple(result)


@pytest.mark.parametrize("command", ["activate", "pause", "archive"])
@pytest.mark.parametrize("grant_change", ["revoked", "expired"])
@pytest.mark.parametrize("original_material", [True, False], ids=["activity", "cash"])
def test_lifecycle_replay_reauthorizes_original_version_with_current_grants(
    alert_case: AlertCase,
    command: Literal["activate", "pause", "archive"],
    grant_change: Literal["revoked", "expired"],
    original_material: bool,
) -> None:
    async def run() -> None:
        case = alert_case
        # This exercises real persistence, reference validation and lifecycle SQL.
        # It never admits an evaluation or uses the fixture's controlled capture.
        service = PostgresAlertService(
            case.sessions, cursor_signing_key=KEY, clock=lambda: case.clock[0]
        )
        # An independent persisted principal keeps the injected expiry clock from
        # changing the shared seed principal's entitlement times in later cases.
        principal_id = uuid4()
        case.principal = replace(
            case.principal,
            principal_id=str(principal_id),
            subject="lifecycle-replay-" + principal_id.hex,
        )
        with case.sessions() as session, session.begin():
            session.add(
                PrincipalModel(
                    id=principal_id,
                    owner_id=UUID(case.principal.owner_id),
                    issuer=case.principal.issuer,
                    subject=case.principal.subject,
                    status="active",
                    created_at=case.clock[0],
                    last_authenticated_at=case.clock[0],
                )
            )
            session.flush()
            provision_principal_scopes(
                session,
                principal_id=principal_id,
                scopes=case.principal.scopes,
                now=case.clock[0],
            )
        assert Scope.ACTIVITY_READ in case.principal.scopes
        grant_deadline = case.clock[0] + timedelta(seconds=60)
        if grant_change == "expired":
            # Trusted entitlement configuration sets a prospective expiry before
            # the original command. No financial or immutable timestamp is edited.
            with case.sessions() as session, session.begin():
                grant = session.get(
                    PrincipalScopeGrantModel, (principal_id, Scope.ACTIVITY_READ.value)
                )
                assert grant is not None and grant.revoked_at is None
                grant.expires_at = grant_deadline

        original_metric = (
            domain.AlertMetric.POSITIVE_DIVIDEND
            if original_material
            else domain.AlertMetric.CASH_WEIGHT
        )
        replacement_metric = (
            domain.AlertMetric.CASH_WEIGHT
            if original_material
            else domain.AlertMetric.POSITIVE_DIVIDEND
        )
        definition = replace(case.definition(), predicate=predicate(original_metric))
        detail = await service.create_rule(
            case.principal,
            app.CreateAlertRuleCommand(account_id=case.account_id, definition=definition),
            idempotency_key=uuid4().hex,
            correlation_id="replay-scope-create",
        )
        original_version = detail.latest_version.id
        key = uuid4().hex
        expected_revision = detail.revision

        async def invoke() -> app.AlertRuleDetail:
            if command == "activate":
                return await service.activate_rule(
                    case.principal,
                    detail.id,
                    original_version,
                    idempotency_key=key,
                    expected_revision=expected_revision,
                    correlation_id="replay-scope-command",
                )
            action = service.pause_rule if command == "pause" else service.archive_rule
            return await action(
                case.principal,
                detail.id,
                idempotency_key=key,
                expected_revision=expected_revision,
                correlation_id="replay-scope-command",
            )

        async def add_replacement(current: app.AlertRuleDetail) -> app.AlertRuleVersionDetail:
            return await service.create_rule_version(
                case.principal,
                current.id,
                app.AlertRuleVersionCommand(
                    definition=replace(definition, predicate=predicate(replacement_metric))
                ),
                idempotency_key=uuid4().hex,
                expected_revision=current.revision,
                correlation_id="replay-scope-version",
            )

        if command != "activate":
            detail = await service.activate_rule(
                case.principal,
                detail.id,
                original_version,
                idempotency_key=uuid4().hex,
                expected_revision=detail.revision,
                correlation_id="replay-scope-initial-activation",
            )
            if command == "archive":
                # Archive cannot later activate another version. A different latest
                # draft still proves replay must use the original active version.
                replacement = await add_replacement(detail)
                detail = await service.get_rule(
                    case.principal, detail.id, query=app.AlertRuleDetailQuery()
                )
                assert detail.latest_version.id == replacement.version.id
            expected_revision = detail.revision
        original_result = await invoke()

        if command != "archive":
            replacement = await add_replacement(original_result)
            current = await service.activate_rule(
                case.principal,
                detail.id,
                replacement.version.id,
                idempotency_key=uuid4().hex,
                expected_revision=replacement.rule_revision,
                correlation_id="replay-scope-different-active-version",
            )
            assert current.active_version is not None
            assert current.active_version.id != original_version
        else:
            current = original_result
        assert current.latest_version.id != original_version

        with case.sessions() as session:
            recorded = session.scalar(
                select(AlertCommandModel).where(
                    AlertCommandModel.owner_id == UUID(case.principal.owner_id),
                    AlertCommandModel.command == command + "_rule",
                    AlertCommandModel.idempotency_key == key,
                )
            )
            assert recorded is not None
            event = session.scalar(
                select(AlertRuleEventModel).where(
                    AlertRuleEventModel.rule_id == detail.id,
                    AlertRuleEventModel.sequence == recorded.resulting_revision,
                )
            )
            assert event is not None and event.version_id == original_version
            assert recorded.resulting_revision == original_result.revision

        before = _stored_state(case)
        allowed = await invoke()
        assert allowed.revision == current.revision
        assert _stored_state(case) == before
        if grant_change == "revoked":
            with case.sessions() as session, session.begin():
                provision_principal_scopes(
                    session,
                    principal_id=principal_id,
                    scopes=case.principal.scopes - {Scope.ACTIVITY_READ},
                    now=case.clock[0],
                )
        else:
            case.clock[0] = grant_deadline + timedelta(seconds=1)
        assert case.principal.expires_at > case.clock[0]
        assert Scope.ACTIVITY_READ in case.principal.scopes
        with case.sessions() as session, session.begin():
            # Prove denial cannot come from token expiry or any baseline write scope.
            authorize_alert_request(
                session,
                case.principal,
                account_id=case.account_id,
                write=True,
                now=case.clock[0],
            )
            grant = session.get(PrincipalScopeGrantModel, (principal_id, Scope.ACTIVITY_READ.value))
            assert grant is not None
            assert (
                grant.revoked_at is not None
                if grant_change == "revoked"
                else grant.expires_at is not None and grant.expires_at < case.clock[0]
            )

        if original_material:
            with pytest.raises(app.AlertServiceError) as error:
                await invoke()
            assert error.value.code is app.AlertServiceErrorCode.ACCESS_DENIED
        else:
            # A later activity version must not impose a new requirement on an
            # original cash command, even when it is now latest/active.
            replay = await invoke()
            assert replay.revision == current.revision
        assert _stored_state(case) == before

        with case.sessions() as session, session.begin():
            provision_principal_scopes(
                session,
                principal_id=principal_id,
                scopes=case.principal.scopes,
                now=case.clock[0],
            )
        replay = await invoke()
        assert replay.revision == current.revision
        assert _stored_state(case) == before
        assert case.control.calls == 0

    asyncio.run(run())
