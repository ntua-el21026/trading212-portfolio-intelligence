"""Bounded append-only execution evidence shared by premium job families."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .premium_models import PremiumAttemptModel, PremiumJobModel


def premium_attempt(
    session: Session,
    job: PremiumJobModel,
    *,
    kind: str,
    event: str,
    number: int,
    token: UUID | None,
    at: datetime,
    failure: str | None = None,
) -> None:
    sequence = (
        session.scalar(
            select(func.max(PremiumAttemptModel.sequence)).where(
                PremiumAttemptModel.owner_id == job.owner_id,
                PremiumAttemptModel.job_id == job.id,
            )
        )
        or 0
    )
    if sequence >= 100:
        raise ValueError("Premium attempt evidence capacity exceeded.")
    session.add(
        PremiumAttemptModel(
            id=uuid4(),
            owner_id=job.owner_id,
            account_id=job.account_id,
            job_id=job.id,
            sequence=sequence + 1,
            kind=kind,
            event=event,
            attempt_number=number,
            claim_token=token,
            failure_code=failure,
            created_at=at,
        )
    )
    session.flush()
