"""Atomic condition application, immutable event identities and notification intents."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from trading212_analytics.alerts import reduce_alert_condition
from trading212_application.alert_jobs import AlertJobInputError, AlertNotificationPayload
from trading212_application.operational_telemetry import AlertPublicationCounts
from trading212_domain.alert_serialization import (
    alert_record_digest,
    decode_alert_condition,
    encode_alert_condition,
    encode_alert_record,
)
from trading212_domain.alerts import (
    AlertEvaluationInput,
    AlertEvaluationResult,
    AlertEventBatchInput,
    AlertNotificationState,
    AlertReason,
)
from trading212_security.principals import AuthorizationError

from .alert_models import (
    AlertConditionModel,
    AlertEvaluationModel,
    AlertEventModel,
    AlertEventTransitionModel,
    InAppNotificationModel,
    NotificationDeliveryJobModel,
    NotificationDeliveryOutboxModel,
    NotificationDestinationModel,
    NotificationDestinationVersionModel,
)


def resolve_episode(
    session: Session,
    event: AlertEventModel,
    *,
    reason: str,
    at: datetime,
    principal_id: UUID | None = None,
    evaluation_id: UUID | None = None,
    note: str | None = None,
) -> None:
    if event.state == "resolved":
        return
    event.state = "resolved"
    event.resolved_at = at
    event.resolution_reason = reason
    event.updated_at = at
    event.revision += 1
    session.add(
        AlertEventTransitionModel(
            id=uuid4(),
            owner_id=event.owner_id,
            account_id=event.account_id,
            created_at=at,
            event_id=event.id,
            evaluation_id=evaluation_id,
            principal_id=principal_id,
            sequence=event.revision,
            kind="resolved",
            reason=reason,
            occurred_at=at,
            note=note,
        )
    )


def _notify(
    session: Session,
    event: AlertEventModel,
    value: AlertEvaluationInput,
    *,
    principal_id: UUID,
    now: datetime,
) -> tuple[int, int]:
    email_unavailable = webhook_unavailable = 0
    external_available = False
    external_requested = False
    for identifier in value.version.definition.destination_ids:
        destination = session.scalar(
            select(NotificationDestinationModel)
            .where(
                NotificationDestinationModel.id == identifier,
                NotificationDestinationModel.owner_id == event.owner_id,
                NotificationDestinationModel.account_id == event.account_id,
            )
            .with_for_update(read=True)
        )
        if destination is None:
            raise AuthorizationError("Alert destination is no longer authorized.")
        version = session.get(NotificationDestinationVersionModel, destination.current_version_id)
        assert version is not None
        if version.channel == "in_app":
            continue
        external_requested = True
        if event.notification_state == "suppressed_cooldown":
            continue
        configured = destination.state == "configured" and version.secret_reference is not None
        external_available |= configured
        if not configured:
            email_unavailable += int(version.channel == "email")
            webhook_unavailable += int(version.channel == "webhook")
        identifier = uuid4()
        payload = AlertNotificationPayload(
            delivery_id=identifier,
            event_id=event.id,
            rule_id=event.rule_id,
            rule_version_id=event.rule_version_id,
        )
        job = NotificationDeliveryJobModel(
            id=identifier,
            owner_id=event.owner_id,
            account_id=event.account_id,
            principal_id=principal_id,
            created_at=now,
            event_id=event.id,
            destination_version_id=version.id,
            channel=version.channel,
            payload_digest=alert_record_digest(payload),
            payload=encode_alert_record(payload),
            expires_at=event.expires_at,
            state="queued" if configured else "failed",
            failure_code=None if configured else "not_configured",
            consumer_attempts=0,
            fence=0,
            lease_id=None,
            consumer_id=None,
            lease_expires_at=None,
            heartbeat_at=None,
            available_at=now,
            completed_at=None if configured else now,
        )
        session.add(job)
        session.flush()
        session.add(
            NotificationDeliveryOutboxModel(
                id=uuid4(),
                owner_id=event.owner_id,
                job_id=job.id,
                created_at=now,
                task_name="notifications.deliver.v1",
                schema_version="1.0.0",
                state="pending" if configured else "failed",
                publication_attempts=0,
                available_at=now,
                claim_token=None,
                dispatcher_id=None,
                claim_expires_at=None,
                published_at=None,
                failure_code=None if configured else "not_configured",
            )
        )
    if external_requested and not external_available and event.notification_state == "eligible":
        event.notification_state = "external_delivery_unavailable"
    session.add(
        InAppNotificationModel(
            id=uuid4(),
            owner_id=event.owner_id,
            account_id=event.account_id,
            event_id=event.id,
            created_at=now,
            eligibility=event.notification_state,
        )
    )
    return email_unavailable, webhook_unavailable


def apply_alert_result(
    session: Session,
    value: AlertEvaluationInput,
    result: AlertEvaluationResult,
    evaluation: AlertEvaluationModel,
    *,
    principal_id: UUID,
    now: datetime,
) -> AlertPublicationCounts:
    condition = session.scalar(
        select(AlertConditionModel)
        .where(AlertConditionModel.rule_version_id == value.version.id)
        .with_for_update()
    )
    assert condition is not None
    state = decode_alert_condition(condition.state_payload)
    digests = tuple(item.deduplication_digest for item in result.event_decisions)
    known = (
        frozenset(
            session.scalars(
                select(AlertEventModel.dedup_digest).where(
                    AlertEventModel.rule_version_id == value.version.id,
                    AlertEventModel.dedup_digest.in_(digests),
                )
            )
        )
        if digests
        else frozenset()
    )
    transition = reduce_alert_condition(
        state,
        result,
        cooldown_seconds=value.version.definition.cooldown_seconds,
        known_event_digests=known,
    )
    # Count every prospective in-app/external job before any event or delivery mutation.
    external_count = (
        session.scalar(
            select(func.count())
            .select_from(NotificationDestinationVersionModel)
            .join(
                NotificationDestinationModel,
                NotificationDestinationModel.current_version_id
                == NotificationDestinationVersionModel.id,
            )
            .where(
                NotificationDestinationModel.owner_id == value.version.owner_id,
                NotificationDestinationModel.account_id == value.version.account_id,
                NotificationDestinationModel.id.in_(value.version.definition.destination_ids),
                NotificationDestinationVersionModel.channel.in_(("email", "webhook")),
            )
        )
        or 0
    )
    prospective = sum(
        1
        + (
            external_count
            if intent.notification_state is not AlertNotificationState.SUPPRESSED_COOLDOWN
            else 0
        )
        for intent in transition.create
    )
    if prospective > 10000:
        raise AlertJobInputError(AlertReason.INPUT_BOUND_EXCEEDED)
    if transition.resolve_episode_id is not None:
        previous = session.get(AlertEventModel, transition.resolve_episode_id)
        assert previous is not None and transition.resolution_reason is not None
        resolve_episode(
            session,
            previous,
            reason=transition.resolution_reason.value,
            at=now,
            evaluation_id=evaluation.id,
        )
    state = transition.state
    observations = (
        {(item.identity, item.revision_id): item for item in value.payload.events}
        if isinstance(value.payload, AlertEventBatchInput)
        else {}
    )
    created = cooldown = 0
    email_unavailable = webhook_unavailable = 0
    deduplicated = (
        sum(
            item.decision is True and item.deduplication_digest in known
            for item in result.event_decisions
        )
        if result.execution_intent.value == "live"
        else 0
    )
    latched = int(
        result.execution_intent.value == "live"
        and result.observation is not None
        and result.decision is True
        and not state.armed
        and not transition.create
    )
    for intent in transition.create:
        existing = session.scalar(
            select(AlertEventModel.id).where(
                AlertEventModel.rule_version_id == value.version.id,
                AlertEventModel.dedup_digest == intent.deduplication_digest,
            )
        )
        if existing is not None:
            deduplicated += 1
            continue
        observation = (
            observations.get((intent.event_identity, intent.revision_id))
            if intent.event_identity is not None
            else None
        )
        correction = (
            session.scalar(
                select(AlertEventModel.id)
                .where(
                    AlertEventModel.rule_version_id == value.version.id,
                    AlertEventModel.event_revision_id == intent.correction_of,
                )
                .order_by(AlertEventModel.created_at.desc())
                .limit(1)
            )
            if intent.correction_of
            else None
        )
        event = AlertEventModel(
            id=uuid4(),
            owner_id=value.version.owner_id,
            account_id=value.version.account_id,
            rule_id=value.version.rule_id,
            rule_version_id=value.version.id,
            evaluation_id=evaluation.id,
            created_at=now,
            occurred_at=observation.economic_at if observation else result.scheduled_for,
            updated_at=now,
            dedup_digest=intent.deduplication_digest,
            episode_key=str(intent.episode_ordinal) if intent.episode_ordinal is not None else None,
            episode_ordinal=intent.episode_ordinal,
            event_identity=intent.event_identity,
            event_revision_id=intent.revision_id,
            family=value.version.definition.predicate.family.value,
            severity=value.version.definition.severity.value,
            state="open",
            revision=1,
            notification_state=intent.notification_state.value,
            opened_at=now,
            resolved_at=None,
            resolution_reason=None,
            correction_of_id=correction,
            payload=encode_alert_record(intent),
            expires_at=evaluation.expires_at,
            purged_at=None,
        )
        session.add(event)
        session.flush()
        session.add(
            AlertEventTransitionModel(
                id=uuid4(),
                owner_id=event.owner_id,
                account_id=event.account_id,
                created_at=now,
                event_id=event.id,
                evaluation_id=evaluation.id,
                principal_id=None,
                sequence=1,
                kind="opened",
                reason=None,
                occurred_at=now,
            )
        )
        if intent.episode_ordinal is not None:
            state = replace(state, open_episode_id=event.id)
        email, webhook = _notify(session, event, value, principal_id=principal_id, now=now)
        email_unavailable += email
        webhook_unavailable += webhook
        created += 1
        cooldown += int(intent.notification_state is AlertNotificationState.SUPPRESSED_COOLDOWN)
    condition.state_payload = encode_alert_condition(state)
    condition.last_applied_scheduled_for = state.last_applied_scheduled_for
    return AlertPublicationCounts(
        created, deduplicated, cooldown, latched, email_unavailable, webhook_unavailable
    )
