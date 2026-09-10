"""Fixed, content-free lifecycle events appended with the guarded transition."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from trading212_domain.reports import ReportFailureCode

from .models import AuditEventModel
from .report_models import ExportJobModel, ReportJobModel


def audit_report_job(
    session: Session,
    job: ReportJobModel | ExportJobModel,
    *,
    event: Literal["created", "completed", "failed", "expired"],
    at: datetime,
    failure: ReportFailureCode | None = None,
) -> None:
    """Call only after the owner-locked transition wins, in its transaction."""
    family = "report" if isinstance(job, ReportJobModel) else "export"
    session.add(
        AuditEventModel(
            id=uuid4(),
            owner_id=job.owner_id,
            principal_id=job.principal_id,
            broker_account_id=job.account_id,
            action=f"{family}.job.{event}",
            resource_type=f"{family}_job",
            resource_id=str(job.id),
            outcome="failed" if event == "failed" else "succeeded",
            occurred_at=at,
            safe_metadata={"failure_code": failure.value} if failure is not None else None,
        )
    )


def audit_report_purge(
    session: Session,
    *,
    owner_id: UUID,
    account_id: UUID,
    input_id: UUID,
    family: Literal["report", "export"],
    reason: Literal["ttl", "source", "owner"],
    at: datetime,
) -> None:
    """Record physical deletion once, after every retained payload is cleared."""
    session.add(
        AuditEventModel(
            id=uuid4(),
            owner_id=owner_id,
            principal_id=None,
            broker_account_id=account_id,
            action=f"{family}.input.purged",
            resource_type=f"{family}_input",
            resource_id=str(input_id),
            outcome="succeeded",
            occurred_at=at,
            safe_metadata={"reason": reason},
        )
    )
