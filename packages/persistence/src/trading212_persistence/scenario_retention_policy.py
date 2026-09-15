"""Metadata-only current retention predicates for fixed scenario source families."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import SQLColumnExpression, and_, literal, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.orm.util import AliasedClass
from sqlalchemy.sql.elements import ColumnElement

from .historical_models import HistoricalInputModel, HistoricalRetentionEventModel
from .premium_models import PremiumRetentionModel, PremiumRunLicenseModel, PremiumRunModel
from .scenario_models import (
    ScenarioAppliedSensitivityModel,
    ScenarioComponentModel,
    ScenarioResultModel,
    ScenarioRunModel,
    ScenarioRunPayloadModel,
    ScenarioRunSensitivityVersionModel,
)
from .scenario_source_models import (
    ScenarioSensitivityEvidenceLinkModel,
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityObservationModel,
    ScenarioSensitivityRetentionModel,
    ScenarioSensitivityVersionModel,
)
from .source_models import ProviderLicenseVersionModel
from .xray_run_models import XrayInputSnapshotModel, XrayRetentionEventModel, XrayRunModel


def _license_restricted(
    owner: SQLColumnExpression[UUID],
    provider: SQLColumnExpression[UUID],
    pinned_id: SQLColumnExpression[UUID],
    created_at: SQLColumnExpression[datetime],
    at: datetime,
) -> ColumnElement[bool]:
    pinned = aliased(ProviderLicenseVersionModel)
    current = aliased(ProviderLicenseVersionModel)
    latest = aliased(ProviderLicenseVersionModel)
    latest_id = (
        select(latest.id)
        .where(latest.owner_id == owner, latest.provider_id == provider, latest.effective_at <= at)
        .order_by(latest.effective_at.desc(), latest.version_number.desc(), latest.id.desc())
        .limit(1)
        .correlate_except(latest)
        .scalar_subquery()
    )

    def permitted(
        license: type[ProviderLicenseVersionModel] | AliasedClass[ProviderLicenseVersionModel],
        identifier: SQLColumnExpression[UUID],
    ) -> ColumnElement[bool]:
        return (
            select(license.id)
            .where(
                license.id == identifier,
                license.owner_id == owner,
                license.provider_id == provider,
                license.effective_at <= at,
                license.store_permission == "allowed",
                license.display_permission == "allowed",
                license.retention_days.is_not(None),
                created_at + license.retention_days * literal(timedelta(days=1)) > at,
            )
            .correlate_except(license)
            .exists()
        )

    return ~and_(permitted(pinned, pinned_id), permitted(current, latest_id))


def sensitivity_version_restricted(at: datetime) -> ColumnElement[bool]:
    version = ScenarioSensitivityVersionModel
    observation = ScenarioSensitivityObservationModel
    evidence = ScenarioSensitivityEvidenceModel
    link = ScenarioSensitivityEvidenceLinkModel
    pending = (
        select(ScenarioSensitivityRetentionModel.id)
        .where(
            ScenarioSensitivityRetentionModel.owner_id == version.owner_id,
            ScenarioSensitivityRetentionModel.version_id == version.id,
        )
        .exists()
    )
    observations = (
        select(observation.id)
        .where(
            observation.owner_id == version.owner_id,
            observation.version_id == version.id,
            _license_restricted(
                observation.owner_id,
                observation.provider_id,
                observation.license_version_id,
                observation.created_at,
                at,
            ),
        )
        .exists()
    )
    evidence_restricted = (
        select(link.id)
        .join(evidence, (evidence.id == link.evidence_id) & (evidence.owner_id == link.owner_id))
        .where(
            link.owner_id == version.owner_id,
            link.version_id == version.id,
            _license_restricted(
                evidence.owner_id,
                evidence.provider_id,
                evidence.license_version_id,
                evidence.created_at,
                at,
            ),
        )
        .exists()
    )
    return or_(
        version.expires_at <= at,
        pending,
        observations,
        evidence_restricted,
        _license_restricted(
            version.owner_id,
            version.provider_id,
            version.license_version_id,
            version.created_at,
            at,
        ),
    )


def scenario_run_restricted(at: datetime) -> ColumnElement[bool]:
    root = PremiumRunModel
    lineage = PremiumRunLicenseModel
    run = ScenarioRunModel
    version = ScenarioSensitivityVersionModel
    used_version = ScenarioRunSensitivityVersionModel
    pending = (
        select(PremiumRetentionModel.id)
        .where(
            PremiumRetentionModel.owner_id == root.owner_id,
            PremiumRetentionModel.run_id == root.id,
            PremiumRetentionModel.completed_at.is_(None),
        )
        .exists()
    )
    license_restricted = (
        select(lineage.id)
        .where(
            lineage.owner_id == root.owner_id,
            lineage.run_id == root.id,
            _license_restricted(
                lineage.owner_id,
                lineage.provider_id,
                lineage.license_version_id,
                root.created_at,
                at,
            ),
        )
        .exists()
    )
    sensitivity = (
        select(used_version.id)
        .join(
            version,
            (version.id == used_version.version_id) & (version.owner_id == used_version.owner_id),
        )
        .where(
            used_version.owner_id == root.owner_id,
            used_version.run_id == root.id,
            sensitivity_version_restricted(at),
        )
        .exists()
    )
    xray_gone = (
        ~select(XrayInputSnapshotModel.id)
        .where(
            XrayInputSnapshotModel.id == run.xray_input_id,
            XrayInputSnapshotModel.owner_id == root.owner_id,
            XrayInputSnapshotModel.canonical_input != b"",
        )
        .exists()
    )
    xray_result_gone = (
        ~select(XrayRunModel.id)
        .where(
            XrayRunModel.id == run.xray_run_id,
            XrayRunModel.owner_id == root.owner_id,
            XrayRunModel.canonical_summary != b"",
        )
        .exists()
    )
    xray_restricted = (
        select(XrayRetentionEventModel.id)
        .where(
            XrayRetentionEventModel.owner_id == root.owner_id,
            XrayRetentionEventModel.input_id == run.xray_input_id,
        )
        .exists()
    )
    historical_gone = (
        ~select(HistoricalInputModel.id)
        .where(
            HistoricalInputModel.owner_id == root.owner_id,
            HistoricalInputModel.id == run.historical_input_id,
            HistoricalInputModel.canonical_input != b"",
        )
        .exists()
    )
    historical_restricted = (
        select(HistoricalRetentionEventModel.id)
        .where(
            HistoricalRetentionEventModel.owner_id == root.owner_id,
            HistoricalRetentionEventModel.input_id == run.historical_input_id,
        )
        .exists()
    )
    parent = (
        select(run.id)
        .where(
            run.owner_id == root.owner_id,
            run.id == root.id,
            or_(
                xray_gone,
                xray_result_gone,
                xray_restricted,
                and_(
                    run.historical_input_id.is_not(None),
                    or_(historical_gone, historical_restricted),
                ),
            ),
        )
        .exists()
    )
    return or_(root.expires_at <= at, pending, license_restricted, sensitivity, parent)


def scenario_run_has_payload(
    owner: SQLColumnExpression[UUID],
    run_id: SQLColumnExpression[UUID],
) -> ColumnElement[bool]:
    """All financial copies count, including a partially purged result."""
    payload = ScenarioRunPayloadModel
    result = ScenarioResultModel
    components = ScenarioComponentModel
    uses = ScenarioAppliedSensitivityModel
    return or_(
        select(payload.id).where(payload.owner_id == owner, payload.run_id == run_id).exists(),
        select(result.id)
        .where(
            result.owner_id == owner,
            result.run_id == run_id,
            or_(
                result.canonical_result != b"",
                select(components.id)
                .where(
                    components.owner_id == owner,
                    components.result_id == result.id,
                )
                .exists(),
                select(uses.id)
                .where(
                    uses.owner_id == owner,
                    uses.result_id == result.id,
                )
                .exists(),
            ),
        )
        .exists(),
    )
