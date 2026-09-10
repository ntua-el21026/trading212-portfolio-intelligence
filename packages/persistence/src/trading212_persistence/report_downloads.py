"""Short-lived opaque grants supplement current authenticated artifact access."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from trading212_application import reports as app

from .models import AuditEventModel
from .report_authorization import ReportAuthorization
from .report_base import ReportStore, StoredArtifact, StoredJob, artifact_metadata, report_error
from .report_models import (
    ArtifactDownloadGrantModel,
    ExportArtifactModel,
    ReportArtifactModel,
    ReportJobModel,
)

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _artifact(
    store: ReportStore,
    session: Session,
    authorization: ReportAuthorization,
    job: StoredJob,
    identifier: UUID,
) -> StoredArtifact:
    store._sources(session, authorization, job)
    if job.state != "succeeded":
        raise report_error(app.ReportServiceErrorCode.INVALID_STATE_TRANSITION)
    model: type[ReportArtifactModel] | type[ExportArtifactModel] = (
        ReportArtifactModel if isinstance(job, ReportJobModel) else ExportArtifactModel
    )
    row = session.scalar(
        select(model)
        .where(
            model.owner_id == job.owner_id,
            model.account_id == job.account_id,
            model.job_id == job.id,
            model.id == identifier,
        )
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise report_error(app.ReportServiceErrorCode.NOT_FOUND)
    if row.purged_at is not None or row.expires_at <= store._now():
        raise report_error(app.ReportServiceErrorCode.ARTIFACT_EXPIRED)
    return row


def create_grant(
    store: ReportStore,
    session: Session,
    authorization: ReportAuthorization,
    job: StoredJob,
    artifact_id: UUID,
) -> app.ArtifactGrant:
    row = _artifact(store, session, authorization, job, artifact_id)
    at = store._now()
    parent = (
        ArtifactDownloadGrantModel.report_artifact_id
        if isinstance(job, ReportJobModel)
        else ArtifactDownloadGrantModel.export_artifact_id
    )
    expired = tuple(
        session.scalars(
            select(ArtifactDownloadGrantModel.id)
            .where(
                ArtifactDownloadGrantModel.owner_id == job.owner_id,
                parent == artifact_id,
                (ArtifactDownloadGrantModel.expires_at <= at)
                | ArtifactDownloadGrantModel.revoked_at.is_not(None),
            )
            .order_by(ArtifactDownloadGrantModel.expires_at, ArtifactDownloadGrantModel.id)
            .limit(100)
        )
    )
    if expired:
        session.execute(
            delete(ArtifactDownloadGrantModel).where(
                ArtifactDownloadGrantModel.owner_id == job.owner_id,
                ArtifactDownloadGrantModel.id.in_(expired),
            )
        )
    active = (
        session.scalar(
            select(func.count())
            .select_from(ArtifactDownloadGrantModel)
            .where(
                ArtifactDownloadGrantModel.owner_id == job.owner_id,
                parent == artifact_id,
                ArtifactDownloadGrantModel.expires_at > at,
                ArtifactDownloadGrantModel.revoked_at.is_(None),
            )
        )
        or 0
    )
    # Fixed per-owner minute bound is additional to the frozen ten active tokens.
    recent = (
        session.scalar(
            select(func.count())
            .select_from(AuditEventModel)
            .where(
                AuditEventModel.owner_id == job.owner_id,
                AuditEventModel.action == "report.artifact.granted",
                AuditEventModel.occurred_at > at - timedelta(minutes=1),
            )
        )
        or 0
    )
    if active >= 10 or recent >= 30:
        raise report_error(app.ReportServiceErrorCode.RATE_LIMITED)
    token = secrets.token_urlsafe(32)
    expires = min(at + timedelta(minutes=5), row.expires_at, job.expires_at)
    if expires <= at:
        raise report_error(app.ReportServiceErrorCode.ARTIFACT_EXPIRED)
    session.add(
        ArtifactDownloadGrantModel(
            id=uuid4(),
            owner_id=job.owner_id,
            account_id=job.account_id,
            created_at=at,
            report_artifact_id=row.id if isinstance(job, ReportJobModel) else None,
            export_artifact_id=row.id if not isinstance(job, ReportJobModel) else None,
            token_digest=hashlib.sha256(token.encode("ascii")).hexdigest(),
            issued_at=at,
            expires_at=expires,
            last_used_at=None,
            revoked_at=None,
        )
    )
    session.add(
        AuditEventModel(
            id=uuid4(),
            owner_id=job.owner_id,
            principal_id=authorization.principal_id,
            broker_account_id=job.account_id,
            action="report.artifact.granted",
            resource_type="artifact",
            resource_id=str(row.id),
            outcome="succeeded",
            occurred_at=at,
            safe_metadata=None,
        )
    )
    session.flush()
    store._sources(session, authorization, job)
    if row.expires_at <= store._now() or expires <= store._now():
        raise report_error(app.ReportServiceErrorCode.ARTIFACT_EXPIRED)
    return app.ArtifactGrant(artifact_id=row.id, token=token, expires_at=expires)


def download_artifact(
    store: ReportStore,
    session: Session,
    authorization: ReportAuthorization,
    job: StoredJob,
    artifact_id: UUID,
    token: str,
) -> app.ReportArtifactDownload:
    if type(token) is not str or _TOKEN.fullmatch(token) is None:
        raise report_error(app.ReportServiceErrorCode.ACCESS_DENIED)
    row = _artifact(store, session, authorization, job, artifact_id)
    parent = (
        ArtifactDownloadGrantModel.report_artifact_id
        if isinstance(job, ReportJobModel)
        else ArtifactDownloadGrantModel.export_artifact_id
    )
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    grant = session.scalar(
        select(ArtifactDownloadGrantModel)
        .where(
            ArtifactDownloadGrantModel.owner_id == job.owner_id,
            ArtifactDownloadGrantModel.account_id == job.account_id,
            parent == row.id,
            ArtifactDownloadGrantModel.token_digest == digest,
            ArtifactDownloadGrantModel.revoked_at.is_(None),
            ArtifactDownloadGrantModel.expires_at > store._now(),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if grant is None or not secrets.compare_digest(grant.token_digest, digest):
        raise report_error(app.ReportServiceErrorCode.ACCESS_DENIED)
    if not 0 < row.byte_length <= 10 * 1024 * 1024:
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    # All identity, permission and grant checks precede the first BYTEA fetch.
    store._sources(session, authorization, job)
    model: type[ReportArtifactModel] | type[ExportArtifactModel] = (
        ReportArtifactModel if isinstance(job, ReportJobModel) else ExportArtifactModel
    )
    content = session.scalar(
        select(model.contents).where(
            model.owner_id == job.owner_id,
            model.job_id == job.id,
            model.id == row.id,
            model.purged_at.is_(None),
        )
    )
    if (
        content is None
        or len(content) != row.byte_length
        or not secrets.compare_digest(
            hashlib.sha256(content).hexdigest(),
            row.content_digest,
        )
    ):
        raise report_error(app.ReportServiceErrorCode.REPORT_UNAVAILABLE)
    store._sources(session, authorization, job)
    if row.expires_at <= store._now() or grant.expires_at <= store._now():
        raise report_error(app.ReportServiceErrorCode.ARTIFACT_EXPIRED)
    grant.last_used_at = store._now()
    session.add(
        AuditEventModel(
            id=uuid4(),
            owner_id=job.owner_id,
            principal_id=authorization.principal_id,
            broker_account_id=job.account_id,
            action="report.artifact.downloaded",
            resource_type="artifact",
            resource_id=str(row.id),
            outcome="succeeded",
            occurred_at=store._now(),
            safe_metadata={"content_digest": row.content_digest, "byte_length": row.byte_length},
        )
    )
    return app.ReportArtifactDownload(
        metadata=artifact_metadata(row), filename=row.filename, content=content
    )
