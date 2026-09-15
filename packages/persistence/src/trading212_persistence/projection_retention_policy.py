"""Cheap metadata rejection for retained projection copies and their source roots.

This predicate never replaces the complete recursive original-source checks in
require_projection_run_sources before job handoff or financial materialization.
"""

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.sql.elements import ColumnElement

from .historical_models import HistoricalInputModel, HistoricalRetentionEventModel
from .premium_models import PremiumRetentionModel, PremiumRunLicenseModel, PremiumRunModel
from .projection_models import ProjectionRunSourceModel, ProjectionSourceLicenseModel
from .scenario_retention_policy import _license_restricted
from .source_models import (
    BenchmarkSnapshotModel,
    PriceSnapshotModel,
    SourceExpiryEventModel,
    SourceRetentionWorkModel,
)


def projection_run_restricted(at: datetime) -> ColumnElement[bool]:
    root, source = PremiumRunModel, ProjectionRunSourceModel
    license_row, link = PremiumRunLicenseModel, ProjectionSourceLicenseModel
    pending = (
        select(PremiumRetentionModel.id)
        .where(
            PremiumRetentionModel.owner_id == root.owner_id,
            PremiumRetentionModel.account_id == root.account_id,
            PremiumRetentionModel.run_id == root.id,
        )
        .exists()
    )
    licenses = (
        select(license_row.id)
        .where(
            license_row.owner_id == root.owner_id,
            license_row.account_id == root.account_id,
            license_row.run_id == root.id,
            _license_restricted(
                license_row.owner_id,
                license_row.provider_id,
                license_row.license_version_id,
                root.created_at,
                at,
            ),
        )
        .exists()
    )
    original_licenses = (
        select(link.id)
        .join(
            license_row,
            (license_row.id == link.run_license_id)
            & (license_row.owner_id == link.owner_id)
            & (license_row.account_id == link.account_id)
            & (license_row.run_id == link.run_id),
        )
        .where(
            link.source_id == source.id,
            link.owner_id == source.owner_id,
            link.account_id == source.account_id,
            link.run_id == source.run_id,
            _license_restricted(
                license_row.owner_id,
                license_row.provider_id,
                license_row.license_version_id,
                source.original_created_at,
                at,
            ),
        )
        .exists()
    )
    history = (
        select(HistoricalInputModel.id)
        .where(
            HistoricalInputModel.id == source.subject_id,
            HistoricalInputModel.owner_id == source.owner_id,
            or_(
                HistoricalInputModel.canonical_input == b"",
                select(HistoricalRetentionEventModel.id)
                .where(
                    HistoricalRetentionEventModel.owner_id == HistoricalInputModel.owner_id,
                    HistoricalRetentionEventModel.input_id == HistoricalInputModel.id,
                )
                .exists(),
            ),
        )
        .exists()
    )
    physical: list[ColumnElement[bool]] = []
    for model, reference in (
        (PriceSnapshotModel, "price_snapshot_id"),
        (BenchmarkSnapshotModel, "benchmark_snapshot_id"),
    ):
        physical.append(
            select(model.id)
            .where(
                model.id == source.subject_id,
                model.owner_id == source.owner_id,
                or_(
                    model.expires_at <= at,
                    _license_restricted(
                        model.owner_id,
                        model.provider_id,
                        model.license_version_id,
                        model.created_at,
                        at,
                    ),
                    *(
                        select(marker.id)
                        .where(
                            marker.owner_id == model.owner_id,
                            getattr(marker, reference) == model.id,
                        )
                        .exists()
                        for marker in (SourceRetentionWorkModel, SourceExpiryEventModel)
                    ),
                ),
            )
            .exists()
        )
    sources = (
        select(source.id)
        .where(
            source.owner_id == root.owner_id,
            source.account_id == root.account_id,
            source.run_id == root.id,
            or_(
                source.source_expires_at <= at,
                original_licenses,
                and_(source.kind == "calibration", or_(history, *physical)),
            ),
        )
        .exists()
    )
    return or_(root.expires_at <= at, pending, licenses, sources)
