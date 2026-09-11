"""Atomic admission of one exact slot with immutable bounded licensed evidence."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session
from trading212_application import alerts as app
from trading212_domain.alert_serialization import encode_alert_input
from trading212_domain.alerts import (
    MAX_ALERT_INPUT_BYTES,
    AlertEvaluationInput,
)

from .alert_authorization import AlertAuthorization
from .alert_base import fail
from .alert_models import (
    AlertEvaluationJobModel,
    AlertEvaluationOutboxModel,
    AlertInputLicenseModel,
    AlertInputSnapshotModel,
    AlertRuleModel,
)
from .alert_sources import authorize_alert_sources, project_alert_dependencies
from .source_store import digest as source_digest


def seal_alert_input(
    session: Session,
    authorization: AlertAuthorization,
    rule: AlertRuleModel,
    value: AlertEvaluationInput,
    *,
    now: datetime,
) -> AlertEvaluationJobModel:
    authorization.check(session, now=now)
    if (value.version.rule_id, value.version.owner_id, value.version.account_id) != (
        rule.id,
        rule.owner_id,
        rule.account_id,
    ):
        fail(app.AlertServiceErrorCode.VALIDATION_FAILED)
    payload = encode_alert_input(value)
    if len(payload) > MAX_ALERT_INPUT_BYTES:
        fail(app.AlertServiceErrorCode.INPUT_BOUND_EXCEEDED)
    digest = hashlib.sha256(payload).hexdigest()
    expires_at = now + timedelta(days=90)
    licenses = {license.id: license for license in value.licenses}
    deadlines = [expires_at]
    for reference in value.source_references:
        if reference.expires_at is not None:
            deadlines.append(reference.expires_at)
        if reference.license_version_id is not None:
            license = licenses.get(str(reference.license_version_id))
            if license is None or license.retention_days is None:
                fail(app.AlertServiceErrorCode.ACCESS_DENIED)
            assert license is not None and license.retention_days is not None
            deadlines.append(reference.first_observed_at + timedelta(days=license.retention_days))
    expires_at = min(deadlines)
    if expires_at <= now:
        fail(app.AlertServiceErrorCode.ACCESS_DENIED)
    snapshot = AlertInputSnapshotModel(
        id=uuid4(),
        owner_id=rule.owner_id,
        account_id=rule.account_id,
        created_at=now,
        rule_version_id=value.version.id,
        scheduled_for=value.scheduled_for,
        source_cutoff_at=value.source_cutoff_at,
        execution_intent=value.execution_intent.value,
        input_digest=digest,
        byte_length=len(payload),
        payload=payload,
        sealed_at=None,
        expires_at=expires_at,
        purged_at=None,
    )
    session.add(snapshot)
    session.flush()
    dependencies = project_alert_dependencies(
        session, authorization, input_id=snapshot.id, value=value, now=now
    )
    session.add_all(dependencies)
    from uuid import UUID

    for license in value.licenses:
        session.add(
            AlertInputLicenseModel(
                id=uuid4(),
                owner_id=rule.owner_id,
                created_at=now,
                input_id=snapshot.id,
                provider_id=UUID(license.provider_id),
                license_version_id=UUID(license.id),
                content_digest=source_digest(license),
            )
        )
    if dependencies:
        snapshot.expires_at = min(
            [
                snapshot.expires_at,
                *(dep.expires_at for dep in dependencies if dep.expires_at is not None),
            ]
        )
    session.flush()
    authorize_alert_sources(session, authorization, input_id=snapshot.id, now=now)
    snapshot.sealed_at = now
    session.flush()
    job = AlertEvaluationJobModel(
        id=uuid4(),
        owner_id=rule.owner_id,
        account_id=rule.account_id,
        principal_id=authorization.principal_id,
        created_at=now,
        rule_id=rule.id,
        rule_version_id=value.version.id,
        input_id=snapshot.id,
        input_digest=digest,
        scheduled_for=value.scheduled_for,
        execution_intent=value.execution_intent.value,
        lifecycle_sequence=rule.lifecycle_sequence,
        expires_at=snapshot.expires_at,
        state="queued",
        failure_code=None,
        consumer_attempts=0,
        fence=0,
        lease_id=None,
        consumer_id=None,
        lease_expires_at=None,
        heartbeat_at=None,
        available_at=now,
        completed_at=None,
        cancelled_by_event_id=None,
    )
    session.add(job)
    session.flush()
    session.add(
        AlertEvaluationOutboxModel(
            id=uuid4(),
            owner_id=rule.owner_id,
            created_at=now,
            job_id=job.id,
            task_name="alerts.evaluate.v1",
            schema_version="1.0.0",
            state="pending",
            publication_attempts=0,
            available_at=now,
            claim_token=None,
            dispatcher_id=None,
            claim_expires_at=None,
            published_at=None,
            failure_code=None,
        )
    )
    return job
