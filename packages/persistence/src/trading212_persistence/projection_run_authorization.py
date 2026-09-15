"""Metadata-only original source authority before projection jobs and private reads."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application.projection import ProjectionErrorCode as Code
from trading212_domain.projection import ProjectionSourcePin

from .premium_models import PremiumRetentionModel, PremiumRunLicenseModel, PremiumRunModel
from .projection_definition_store import ProjectionStorageError
from .projection_input_store import ProjectionInputStore
from .projection_models import ProjectionRunModel, ProjectionRunSourceModel
from .report_authorization import ReportAuthorization


def require_projection_run_sources(
    store: ProjectionInputStore,
    session: Session,
    auth: ReportAuthorization,
    root: PremiumRunModel,
    run: ProjectionRunModel,
) -> datetime:
    """Check all declared source identities and original/current rights without BYTEA."""
    auth = store.authority(session, auth)
    if (
        root.kind != "projection"
        or root.id != run.id
        or (root.owner_id, root.account_id) != (auth.owner_id, auth.account_id)
        or (run.owner_id, run.account_id) != (auth.owner_id, auth.account_id)
        or not run.sealed
        or run.capture_digest != root.input_digest
        or run.created_at != root.created_at
        or root.created_at > store._now()
    ):
        raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
    if (
        root.expires_at <= store._now()
        or session.scalar(
            select(PremiumRetentionModel.id)
            .where(
                PremiumRetentionModel.owner_id == auth.owner_id,
                PremiumRetentionModel.account_id == auth.account_id,
                PremiumRetentionModel.run_id == root.id,
            )
            .limit(1)
        )
        is not None
    ):
        raise ProjectionStorageError(Code.RUN_EXPIRED)
    sources = tuple(
        session.scalars(
            select(ProjectionRunSourceModel)
            .where(
                ProjectionRunSourceModel.run_id == root.id,
                ProjectionRunSourceModel.owner_id == auth.owner_id,
                ProjectionRunSourceModel.account_id == auth.account_id,
            )
            .order_by(ProjectionRunSourceModel.kind, ProjectionRunSourceModel.subject_id)
            .limit(258)
        )
    )
    if len(sources) != run.source_count or len(sources) > 257:
        raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
    pins = tuple(
        ProjectionSourcePin(subject_id=str(row.subject_id), content_digest=row.content_digest)
        for row in sources
        if row.kind == "calibration"
    )
    authorized, deadline = store.sources.authorize_sources(
        session, auth, pins, snapshot_id=run.snapshot_id, retained_at=root.created_at
    )
    expected = {(str(row.role), row.subject_id): row for row in authorized}
    if len(expected) != len(sources) or any(
        (header := expected.get((row.kind, row.subject_id))) is None
        or row.content_digest != header.content_digest
        or row.original_created_at != header.original_created_at
        for row in sources
    ):
        raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
    licenses = tuple(
        session.scalars(
            select(PremiumRunLicenseModel)
            .where(
                PremiumRunLicenseModel.run_id == root.id,
                PremiumRunLicenseModel.owner_id == auth.owner_id,
                PremiumRunLicenseModel.account_id == auth.account_id,
            )
            .limit(8193)
        )
    )
    expected_licenses = {identifier for row in authorized for identifier in row.license_version_ids}
    if (
        len(licenses) > 8192
        or len(licenses) != len(expected_licenses)
        or {row.license_version_id for row in licenses} != expected_licenses
    ):
        raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
    for row in licenses:
        store.sources._license(session, auth, row.license_version_id, root.created_at)
        pinned = store.sources._sources._license(session, auth.owner_id, row.license_version_id)
        if str(row.provider_id) != pinned.provider_id:
            raise ProjectionStorageError(Code.PROJECTION_UNAVAILABLE)
    if (
        root.expires_at > deadline
        or root.expires_at <= store._now()
        or any(row.source_expires_at <= store._now() for row in sources)
    ):
        raise ProjectionStorageError(Code.RUN_EXPIRED)
    auth.check(session, now=store._now())
    return deadline
