"""Fixed operational cursors for legacy report cleanup, never read authority."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .historical_models import HistoricalDependencyModel
from .premium_models import PremiumRunLicenseModel
from .report_models import ReportInputLicenseModel
from .scenario_models import (
    ScenarioRunSensitivityEvidenceModel,
    ScenarioRunSensitivityObservationModel,
    ScenarioRunSensitivityVersionModel,
)
from .types import UTCDateTime


class LegacyReportRetentionSweepModel(Base):
    __tablename__ = "legacy_report_retention_sweeps"
    __table_args__ = (CheckConstraint("id=1", name="singleton"),)
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    after_id: Mapped[UUID | None] = mapped_column(Uuid())
    pending_after_id: Mapped[UUID | None] = mapped_column(Uuid())
    deferred: Mapped[bool] = mapped_column(Boolean)


class LegacyReportRetentionScanModel(Base):
    __tablename__ = "legacy_report_retention_scans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "account_id", "input_id"],
            [
                "report_input_snapshots.owner_id",
                "report_input_snapshots.account_id",
                "report_input_snapshots.id",
            ],
            ondelete="RESTRICT",
            name="fk_legacy_report_scan_input",
        ),
        CheckConstraint("phase BETWEEN 1 AND 9 AND policy_epoch>=0", name="phase_bound"),
        CheckConstraint(
            (
                "(phase=5 OR (evidence_id IS NULL AND evidence_cursor IS NULL)) AND "
                "(evidence_cursor IS NULL OR evidence_id IS NOT NULL)"
            ),
            name="evidence_phase",
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), primary_key=True
    )
    account_id: Mapped[UUID] = mapped_column(Uuid())
    input_id: Mapped[UUID] = mapped_column(Uuid())
    run_id: Mapped[UUID] = mapped_column(Uuid())
    historical_input_id: Mapped[UUID | None] = mapped_column(Uuid())
    phase: Mapped[int] = mapped_column(SmallInteger)
    cursor: Mapped[UUID | None] = mapped_column(Uuid())
    evidence_id: Mapped[UUID | None] = mapped_column(Uuid())
    evidence_cursor: Mapped[UUID | None] = mapped_column(Uuid())
    policy_epoch: Mapped[int] = mapped_column(BigInteger)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    earliest_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_policy_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


# These are exact parent/id ordering indices for the finite scan phases; no
# filtered cross-parent collection is sorted before LIMIT.
Index(
    "ix_legacy_report_licenses_input",
    ReportInputLicenseModel.owner_id,
    ReportInputLicenseModel.input_id,
    ReportInputLicenseModel.id,
)
Index(
    "ix_legacy_report_premium_licenses",
    PremiumRunLicenseModel.owner_id,
    PremiumRunLicenseModel.run_id,
    PremiumRunLicenseModel.id,
)
Index(
    "ix_legacy_report_history_membership",
    HistoricalDependencyModel.owner_id,
    HistoricalDependencyModel.input_id,
    HistoricalDependencyModel.registered_evidence_id,
)
Index(
    "ix_legacy_report_scenario_versions",
    ScenarioRunSensitivityVersionModel.owner_id,
    ScenarioRunSensitivityVersionModel.run_id,
    ScenarioRunSensitivityVersionModel.id,
)
Index(
    "ix_legacy_report_scenario_observations",
    ScenarioRunSensitivityObservationModel.owner_id,
    ScenarioRunSensitivityObservationModel.run_id,
    ScenarioRunSensitivityObservationModel.id,
)
Index(
    "ix_legacy_report_scenario_evidence",
    ScenarioRunSensitivityEvidenceModel.owner_id,
    ScenarioRunSensitivityEvidenceModel.run_id,
    ScenarioRunSensitivityEvidenceModel.id,
)

LEGACY_REPORT_RETENTION_MODELS = (LegacyReportRetentionSweepModel, LegacyReportRetentionScanModel)
