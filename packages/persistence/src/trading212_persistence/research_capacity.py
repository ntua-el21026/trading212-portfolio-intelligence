"""Closed research admission checks over shared owner capacity; SQL remains the backstop."""

from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from trading212_application.research import ResearchErrorCode, ResearchServiceError

from .premium_models import PremiumCapacityModel
from .projection_models import AssumptionVersionModel, GoalVersionModel
from .report_authorization import ReportAuthorization
from .research_models import (
    ResearchCapacityModel,
    ResearchEventRevisionModel,
    ResearchItemModel,
    ResearchNoteRevisionModel,
    ResearchSourceVersionModel,
    ResearchWitnessModel,
)
from .risk_models import RiskVersionModel
from .scenario_models import ScenarioVersionModel


def admit_research(
    session: Session,
    auth: ReportAuthorization,
    kind: Literal["source", "event", "receipt", "item", "note"],
    *,
    payload_bytes: int = 0,
) -> None:
    if (
        kind not in ("source", "event", "receipt", "item", "note")
        or type(payload_bytes) is not int
        or payload_bytes < 0
    ):
        raise ResearchServiceError(ResearchErrorCode.VALIDATION_FAILED)
    capacity = session.scalar(
        select(PremiumCapacityModel)
        .where(PremiumCapacityModel.owner_id == auth.owner_id)
        .with_for_update()
    )
    local = session.scalar(
        select(ResearchCapacityModel)
        .where(ResearchCapacityModel.owner_id == auth.owner_id)
        .with_for_update()
    )
    if (
        capacity is not None
        and capacity.reserved_bytes + capacity.retained_bytes + payload_bytes > 268435456
    ):
        raise ResearchServiceError(ResearchErrorCode.RATE_LIMITED)
    if local is not None and local.retained_bytes + payload_bytes > 268435456:
        raise ResearchServiceError(ResearchErrorCode.RATE_LIMITED)
    if kind in ("source", "event", "receipt"):
        actual = sum(
            session.scalar(
                select(func.count()).select_from(model).where(model.owner_id == auth.owner_id)
            )
            or 0
            for model in (
                ResearchSourceVersionModel,
                ResearchEventRevisionModel,
                ResearchWitnessModel,
            )
        )
        recorded = 0 if local is None else local.source_revisions + local.event_revisions
        if max(actual, recorded) >= 10000:
            raise ResearchServiceError(ResearchErrorCode.RATE_LIMITED)
    elif kind == "item":
        actual = (
            session.scalar(
                select(func.count())
                .select_from(ResearchItemModel)
                .where(ResearchItemModel.owner_id == auth.owner_id)
            )
            or 0
        )
        if max(actual, 0 if local is None else local.item_headers) >= 10000:
            raise ResearchServiceError(ResearchErrorCode.RATE_LIMITED)
    elif kind == "note":
        actual = sum(
            session.scalar(
                select(func.count()).select_from(model).where(model.owner_id == auth.owner_id)
            )
            or 0
            for model in (
                RiskVersionModel,
                ScenarioVersionModel,
                AssumptionVersionModel,
                GoalVersionModel,
                ResearchNoteRevisionModel,
            )
        )
        if max(actual, 0 if capacity is None else capacity.definition_versions) >= 512:
            raise ResearchServiceError(ResearchErrorCode.RATE_LIMITED)
