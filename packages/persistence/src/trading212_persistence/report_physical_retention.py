"""Drain only operational source-copy flags after all report bytes have gone."""

from typing import Literal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .report_models import ReportInputDependencyModel
from .source_retention import SourcePurgeBudget

LegacyReportWitnessKind = Literal[
    "physical",
    "root",
    "report_license",
    "premium_license",
    "parents",
    "history",
    "version",
    "observation",
    "evidence",
]
LegacyReportWitness = tuple[LegacyReportWitnessKind, UUID]
# The per-row immutable guard independently probes <=24 report participants,
# exact pending marker and fixed scope/FK rows. Metadata selection is separate.
REPORT_SOURCE_FLAG_INSPECTIONS = 32
LEGACY_REPORT_POINT_INSPECTIONS = 16
LEGACY_REPORT_ROOT_INSPECTIONS = 8
LEGACY_REPORT_PARENT_INSPECTIONS = 8


def clear_report_source_flags(
    session: Session,
    owner: UUID,
    input_id: UUID,
    *,
    budget: SourcePurgeBudget,
) -> bool:
    model = ReportInputDependencyModel
    predicate = (
        (model.owner_id == owner) & (model.input_id == input_id) & model.copy_pending.is_(True)
    )
    while budget.metadata_limit:
        limit = min(512, budget.rows_inspected) // (1 + REPORT_SOURCE_FLAG_INSPECTIONS)
        if limit < 1:
            return False
        ids = tuple(
            session.scalars(
                select(model.id).where(predicate).order_by(model.id).limit(limit).with_for_update()
            )
        )
        if not budget.inspect(rows=max(1, len(ids))):
            return False
        if not ids:
            return True
        if not budget.inspect(rows=len(ids) * REPORT_SOURCE_FLAG_INSPECTIONS):
            return False
        session.execute(
            update(model).where(predicate, model.id.in_(ids)).values(copy_pending=False)
        )
    return False
