"""Synthetic small canonical results and owner/fence metadata for store regressions."""

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.projection import calculate_projection_chunk
from trading212_domain.projection_result import ProjectionCalculation
from trading212_persistence import projection_models as m
from trading212_persistence.premium_models import PremiumJobModel, PremiumRunModel
from trading212_persistence.projection_input_store import (
    CapturedProjectionInputs,
    projection_run_header,
)
from trading212_persistence.projection_result_store import ProjectionResultStore
from trading212_persistence.projection_retained_codec import (
    pack_projection_chunk,
    pack_projection_input,
)
from trading212_persistence.projection_source_store import ProjectionSourceBundle
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_security.principals import Scope

from tests.unit.application.projection_presentation_factories import retained

AT = datetime(2026, 8, 31, 12, tzinfo=UTC)
OWNER, ACTOR, RUN, JOB, LEASE = (UUID(int=index) for index in range(700, 705))


def records() -> tuple[
    CapturedProjectionInputs,
    ProjectionCalculation,
    ReportAuthorization,
    PremiumRunModel,
    m.ProjectionRunModel,
    PremiumJobModel,
]:
    saved = retained(observed=False, source_count=0)
    captured = CapturedProjectionInputs(
        plan=saved.capture,
        stored=pack_projection_input(saved.capture),
        sources=ProjectionSourceBundle(
            snapshot=None, sources=(), expires_at=AT + timedelta(days=30), license_version_ids=()
        ),
    )
    account = saved.account_id
    auth = ReportAuthorization(
        principal_id=ACTOR,
        owner_id=OWNER,
        account_id=account,
        required_scopes=frozenset(
            {Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.PROJECTIONS_WRITE}
        ),
        expires_at=AT + timedelta(days=1),
        issuer="synthetic.issuer",
        subject="worker",
    )
    root = PremiumRunModel(
        id=RUN,
        owner_id=OWNER,
        account_id=account,
        kind="projection",
        command_id=UUID(int=705),
        actor_principal_id=ACTOR,
        input_digest=captured.input_digest,
        method_version="1.0.0",
        schema_version="1.0.0",
        numerical_profile="premium_decimal96_q18_v1",
        created_at=AT,
        expires_at=AT + timedelta(days=30),
        reserved_bytes=33554432,
        retained_bytes=0,
    )
    run = m.ProjectionRunModel(
        id=RUN,
        owner_id=OWNER,
        account_id=account,
        created_at=AT,
        sealed=True,
        **projection_run_header(captured.plan, 0),
    )
    job = PremiumJobModel(
        id=JOB,
        run_id=RUN,
        owner_id=OWNER,
        account_id=account,
        created_at=AT,
        state="running",
        consumer_attempts=2,
        lease_token=LEASE,
        heartbeat_at=AT,
        deadline_at=AT + timedelta(seconds=60),
        lease_expires_at=AT + timedelta(seconds=60),
        consumer_id="synthetic-worker",
        failure_code=None,
        completed_at=None,
    )
    return captured, saved.calculation, auth, root, run, job


def store() -> tuple[ProjectionResultStore, MagicMock]:
    session = MagicMock(spec=Session)
    value = ProjectionResultStore(
        cast(sessionmaker[Session], MagicMock()),
        cursor_signing_key=b"synthetic-projection-key" * 2,
        clock=lambda: AT,
    )
    return value, session


def chunk_header(
    captured: CapturedProjectionInputs,
    *,
    start: int = 0,
    count: int = 2,
    variant: str = "baseline",
    identifier: int = 800,
) -> m.ProjectionChunkModel:
    from trading212_domain.projection import ProjectionVariant

    chunk = calculate_projection_chunk(
        captured.plan.inputs, start, count, variant=cast(ProjectionVariant, variant)
    )
    packed = pack_projection_chunk(chunk, expected_inputs=captured.plan.inputs)
    return m.ProjectionChunkModel(
        id=UUID(int=identifier),
        run_id=RUN,
        job_id=JOB,
        owner_id=OWNER,
        account_id=captured.plan.selection.account_id,
        created_at=AT,
        lease_token=UUID(int=999),
        consumer_attempt=1,
        variant=variant,
        first_path=start,
        path_count=count,
        input_digest=packed.input_digest,
        content_digest=packed.content_digest,
        byte_length=packed.byte_length,
        canonical_chunk=packed.canonical_chunk,
        sealed=True,
    )
