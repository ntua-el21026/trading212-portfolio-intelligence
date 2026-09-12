"""Fixed metadata-only delivery payloads and current destination authorization."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application import alert_jobs as jobs
from trading212_application import alerts as app
from trading212_application.operational_telemetry import Operation, record_operation
from trading212_domain.alert_serialization import decode_alert_record
from trading212_domain.alerts import AlertReason

from .alert_base import alert_owner_lock
from .alert_job_transitions import AlertJobTransitions
from .alert_models import (
    NotificationDeliveryJobModel,
    NotificationDestinationModel,
    NotificationDestinationVersionModel,
)


class PostgresAlertNotificationStore(AlertJobTransitions):
    async def load_notification_payload(
        self, claim: jobs.AlertNotificationJobClaim
    ) -> jobs.AlertNotificationPayload:
        def execute() -> jobs.AlertNotificationPayload:
            with self._sessions() as session, session.begin():
                alert_owner_lock(session, claim.message.owner_id)
                job = self._live(session, claim)
                if not isinstance(job, NotificationDeliveryJobModel):
                    raise jobs.AlertJobInputError(AlertReason.LEASE_EXPIRED)
                self._job_authorization(session, job)
                payload = job.payload
                if hashlib.sha256(payload).hexdigest() != job.payload_digest:
                    raise jobs.AlertJobInputError(AlertReason.AMBIGUOUS_SOURCE)
                result = decode_alert_record(payload, jobs.AlertNotificationPayload)
                if (result.delivery_id, result.event_id) != (job.id, job.event_id):
                    raise jobs.AlertJobInputError(AlertReason.AMBIGUOUS_SOURCE)
                return result

        return await self._worker_run(execute)

    async def complete_notification_job(
        self, claim: jobs.AlertNotificationJobClaim, *, receipt: jobs.AlertDeliveryReceipt
    ) -> bool:
        if receipt.delivery_id != claim.message.delivery_id:
            raise jobs.AlertJobInputError(AlertReason.AMBIGUOUS_SOURCE)
        if receipt.outcome is not jobs.AlertDeliveryOutcome.ACCEPTED:
            return await self.fail_notification_job(
                claim,
                failure=receipt.reason or AlertReason.NOT_CONFIGURED,
                retryable=receipt.outcome is jobs.AlertDeliveryOutcome.RETRYABLE_FAILURE,
            )

        def execute() -> str | None:
            with self._sessions() as session, session.begin():
                alert_owner_lock(session, claim.message.owner_id)
                job = self._live(session, claim)
                if not isinstance(job, NotificationDeliveryJobModel):
                    return None
                self._job_authorization(session, job)
                if receipt.observed_at > self._now() or receipt.observed_at < job.created_at:
                    raise jobs.AlertJobInputError(AlertReason.AMBIGUOUS_SOURCE)
                job.state = "succeeded"
                job.completed_at = self._now()
                job.failure_code = None
                job.lease_id = None
                job.lease_expires_at = None
                job.consumer_id = None
                self._attempt(
                    session,
                    job,
                    phase="consumer",
                    attempt=job.consumer_attempts,
                    outcome="succeeded",
                )
                self._audit_job(session, job, "completed")
                return job.channel

        channel = await self._worker_run(execute)
        if channel is None:
            return False
        operation = {
            "email": Operation.EMAIL_DELIVERY,
            "webhook": Operation.WEBHOOK_DELIVERY,
        }[channel]
        record_operation(operation, "accepted")
        return True


def provision_notification_destination(
    session: Session,
    *,
    owner_id: UUID,
    account_id: UUID,
    configuration_key: str,
    channel: app.NotificationChannel,
    label: str,
    secret_reference: str | None,
    state: app.NotificationDestinationState,
    now: datetime,
) -> UUID:
    """Trusted server configuration only; public commands never accept delivery URLs/secrets."""
    if not configuration_key or len(configuration_key) > 120 or not label or len(label) > 120:
        raise ValueError("A bounded configured destination is required.")
    if secret_reference is not None and (not secret_reference or len(secret_reference) > 200):
        raise ValueError("A bounded opaque secret reference is required.")
    alert_owner_lock(session, owner_id)
    row = session.scalar(
        select(NotificationDestinationModel)
        .where(
            NotificationDestinationModel.owner_id == owner_id,
            NotificationDestinationModel.account_id == account_id,
            NotificationDestinationModel.configuration_key == configuration_key,
        )
        .with_for_update()
    )
    if row is None:
        row = NotificationDestinationModel(
            id=uuid4(),
            owner_id=owner_id,
            account_id=account_id,
            created_at=now,
            configuration_key=configuration_key,
            state=state.value,
            current_version_id=None,
        )
        session.add(row)
        session.flush()
        number = 1
    else:
        current = session.get(NotificationDestinationVersionModel, row.current_version_id)
        assert current is not None
        if (current.channel, current.label, current.secret_reference, row.state) == (
            channel.value,
            label,
            secret_reference,
            state.value,
        ):
            return row.id
        number = current.version_number + 1
    import json

    digest = hashlib.sha256(
        json.dumps(
            [channel.value, label, configuration_key, secret_reference],
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    version = NotificationDestinationVersionModel(
        id=uuid4(),
        owner_id=owner_id,
        account_id=account_id,
        created_at=now,
        destination_id=row.id,
        version_number=number,
        channel=channel.value,
        label=label,
        configuration_key=configuration_key,
        secret_reference=secret_reference,
        content_digest=digest,
    )
    session.add(version)
    session.flush()
    row.current_version_id = version.id
    row.state = state.value
    return row.id
