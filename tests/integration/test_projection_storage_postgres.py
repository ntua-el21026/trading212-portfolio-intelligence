"""Real PostgreSQL normalized capture/checkpoint/result publication backstops.

These tiny modeled fixtures call the accepted capture and numerical kernels. They
exercise SQL storage contracts only and do not claim worker/service integration.
"""

from dataclasses import dataclass, fields
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError
from trading212_analytics.projection import calculate_projection_chunk, finalize_projection
from trading212_application.projection_capture import (
    ProjectionAssumptionVersion,
    ProjectionCapturePlan,
    ProjectionDatedSchedule,
    ProjectionInitialSelection,
    ProjectionRunSelection,
    projection_capture_bytes,
    projection_capture_digest,
)
from trading212_domain.projection import ProjectionAllocation
from trading212_domain.projection_result import ProjectionCalculation, ProjectionChunk
from trading212_domain.projection_serialization import projection_canonical_bytes
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.premium_models import (
    PremiumAuditModel,
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRunModel,
)
from trading212_persistence.projection_models import (
    ProjectionCalendarBoundaryModel,
    ProjectionChunkModel,
    ProjectionDistributionModel,
    ProjectionDistributionQuantileModel,
    ProjectionHistogramBinModel,
    ProjectionHistogramModel,
    ProjectionInputModel,
    ProjectionPathModel,
    ProjectionPointAssetModel,
    ProjectionPointModel,
    ProjectionResultModel,
    ProjectionRunAllocationModel,
    ProjectionRunModel,
    ProjectionZeroPivotModel,
)
from trading212_persistence.report_models import ApplicationCommandIdentityModel

from tests.integration.test_migrations import database_engine as database_engine
from tests.integration.test_projection_definitions_postgres import ProjectionDefinitionCase, finish
from tests.integration.test_projection_definitions_postgres import (
    projection_definition_case as projection_definition_case,
)

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


@dataclass
class StoredProjectionFixture:
    case: ProjectionDefinitionCase
    plan: ProjectionCapturePlan
    root: PremiumRunModel
    run: ProjectionRunModel
    job: PremiumJobModel
    outbox: PremiumOutboxModel


def queued_projection(c: ProjectionDefinitionCase) -> StoredProjectionFixture:
    request = c.assumption()
    head = c.store.publish_assumption_set(c.session, c.auth, request)
    saved = c.store.read_assumption_version(c.session, c.auth, head.current_version_id)
    selected = ProjectionRunSelection(
        account_id=c.auth.account_id,
        assumption_version_id=saved.id,
        initial=ProjectionInitialSelection(
            kind="modeled_value",
            modeled_value=Money(Decimal(1000), CurrencyCode("EUR")),
            modeled_anchor_date=c.now.date(),
        ),
        schedule=ProjectionDatedSchedule(base_monthly=Money(Decimal(10), CurrencyCode("EUR"))),
        seed=19,
        months=2,
        paths=2,
        retained_months=(0, 1, 2),
        allocation=tuple(
            ProjectionAllocation(key=a.key, weight=a.weight) for a in saved.content.assets
        ),
    )
    plan = ProjectionCapturePlan(
        selection=selected,
        assumption_version=ProjectionAssumptionVersion(
            account_id=saved.account_id,
            version_id=saved.id,
            content=saved.content,
            content_digest=saved.content_digest,
        ),
    )
    c.store.reserve_run_capacity(c.session, c.auth)
    identifier = uuid4()
    command_id = uuid4()
    c.session.add(
        ApplicationCommandIdentityModel(
            id=command_id,
            owner_id=c.auth.owner_id,
            account_id=c.auth.account_id,
            command="projection.run.create.v1",
            idempotency_key=str(uuid4()),
            command_digest=sha256(projection_capture_bytes(plan)).hexdigest(),
            premium_resource_id=identifier,
            premium_actor_id=c.auth.principal_id,
            premium_correlation_id="projection-storage-fixture",
            report_job_id=None,
            export_job_id=None,
            created_at=c.now,
        )
    )
    c.session.flush()
    c.session.add(
        PremiumAuditModel(
            id=uuid4(),
            owner_id=c.auth.owner_id,
            account_id=c.auth.account_id,
            command_id=command_id,
            kind="created",
            created_at=c.now,
        )
    )
    root = PremiumRunModel(
        id=identifier,
        owner_id=c.auth.owner_id,
        account_id=c.auth.account_id,
        kind="projection",
        command_id=command_id,
        actor_principal_id=c.auth.principal_id,
        input_digest=projection_capture_digest(plan),
        expires_at=c.now + timedelta(days=1),
        method_version="1.0.0",
        schema_version="1.0.0",
        numerical_profile="premium_decimal96_q18_v1",
        reserved_bytes=33554432,
        retained_bytes=0,
        created_at=c.now,
    )
    c.session.add(root)
    c.session.flush()
    run = ProjectionRunModel(
        id=root.id,
        owner_id=c.auth.owner_id,
        account_id=c.auth.account_id,
        assumption_version_id=saved.id,
        assumption_digest=saved.content_digest,
        goal_version_id=None,
        goal_digest=None,
        numerical_input_digest=plan.numerical_input_digest,
        capture_digest=root.input_digest,
        seed=selected.seed,
        months=2,
        path_count=2,
        asset_count=2,
        retained_point_count=3,
        variant_count=1,
        source_count=0,
        initial_kind="modeled_value",
        snapshot_id=None,
        snapshot_digest=None,
        snapshot_valuation_at=None,
        anchor_date=plan.calendar.anchor_date,
        reporting_currency="EUR",
        calendar_rule=plan.calendar.rule,
        sealed=False,
        created_at=c.now,
    )
    c.session.add(run)
    c.session.flush()
    captured = projection_capture_bytes(plan)
    numerical = projection_canonical_bytes(plan.inputs)
    c.session.add(
        ProjectionInputModel(
            id=uuid4(),
            owner_id=c.auth.owner_id,
            account_id=c.auth.account_id,
            run_id=run.id,
            initial_value=plan.inputs.initial.value.amount,
            base_monthly=plan.inputs.schedule.base_monthly.amount,
            annual_growth=plan.inputs.schedule.annual_growth,
            contribution_delta=None,
            annual_mean_log_delta=None,
            pause_count=0,
            entry_count=0,
            capture_bytes=len(captured),
            input_bytes=len(numerical),
            canonical_capture=captured,
            canonical_input=numerical,
            created_at=c.now,
        )
    )
    for i, a in enumerate(selected.allocation):
        c.session.add(
            ProjectionRunAllocationModel(
                id=uuid4(),
                owner_id=c.auth.owner_id,
                account_id=c.auth.account_id,
                run_id=run.id,
                asset_index=i,
                asset_key=a.key,
                weight=a.weight,
                created_at=c.now,
            )
        )
    for i, on in enumerate(plan.calendar.boundaries):
        c.session.add(
            ProjectionCalendarBoundaryModel(
                id=uuid4(),
                owner_id=c.auth.owner_id,
                account_id=c.auth.account_id,
                run_id=run.id,
                month=i,
                on=on,
                point_index=i,
                created_at=c.now,
            )
        )
    job = PremiumJobModel(
        id=uuid4(),
        owner_id=c.auth.owner_id,
        account_id=c.auth.account_id,
        run_id=run.id,
        state="queued",
        consumer_attempts=0,
        created_at=c.now,
    )
    c.session.add(job)
    c.session.flush()
    outbox = PremiumOutboxModel(
        id=uuid4(),
        owner_id=c.auth.owner_id,
        account_id=c.auth.account_id,
        job_id=job.id,
        task_name="projections.calculate.v1",
        state="pending",
        publication_attempts=0,
        available_at=c.now,
        created_at=c.now,
    )
    c.session.add(outbox)
    c.session.flush()
    run.sealed = True
    finish(c.session)
    return StoredProjectionFixture(c, plan, root, run, job, outbox)


def claim(value: StoredProjectionFixture) -> UUID:
    job = value.job
    at = value.case.now
    token = uuid4()
    job.state = "running"
    job.consumer_attempts = 1
    job.lease_token = token
    job.lease_expires_at = at + timedelta(seconds=60)
    job.heartbeat_at = at
    job.deadline_at = at + timedelta(seconds=240)
    job.consumer_id = "synthetic-projection-worker"
    value.case.session.flush()
    return token


def store_chunk(
    value: StoredProjectionFixture,
    chunk: ProjectionChunk,
    *,
    token: UUID | None = None,
    corrupt_money: bool = False,
    missing_point: bool = False,
) -> ProjectionChunkModel:
    c = value.case
    payload = projection_canonical_bytes(chunk)
    row = ProjectionChunkModel(
        id=uuid4(),
        owner_id=c.auth.owner_id,
        account_id=c.auth.account_id,
        run_id=value.run.id,
        job_id=value.job.id,
        lease_token=token or value.job.lease_token,
        consumer_attempt=value.job.consumer_attempts,
        variant=chunk.variant,
        first_path=chunk.paths[0].index,
        path_count=len(chunk.paths),
        input_digest=chunk.input_digest,
        content_digest=sha256(payload).hexdigest(),
        byte_length=len(payload),
        canonical_chunk=payload,
        sealed=False,
        created_at=c.now,
    )
    c.session.add(row)
    c.session.flush()
    for path in chunk.paths:
        stored = ProjectionPathModel(
            id=uuid4(),
            owner_id=c.auth.owner_id,
            account_id=c.auth.account_id,
            run_id=value.run.id,
            chunk_id=row.id,
            variant=chunk.variant,
            path_index=path.index,
            first_unpaid_month=path.first_unpaid_month,
            created_at=c.now,
        )
        c.session.add(stored)
        c.session.flush()
        for i, point in enumerate(path.points):
            if missing_point and path.index == chunk.paths[0].index and i == 0:
                continue
            attributes = {
                f.name: getattr(point, f.name) for f in fields(point) if f.name != "assets"
            }
            if corrupt_money and path.index == chunk.paths[0].index and i == 1:
                attributes["investment_effect"] = point.investment_effect + Decimal(1)
            retained = ProjectionPointModel(
                id=uuid4(),
                owner_id=c.auth.owner_id,
                account_id=c.auth.account_id,
                run_id=value.run.id,
                path_id=stored.id,
                point_index=i,
                created_at=c.now,
                **attributes,
            )
            c.session.add(retained)
            c.session.flush()
            for j, asset in enumerate(point.assets):
                c.session.add(
                    ProjectionPointAssetModel(
                        id=uuid4(),
                        owner_id=c.auth.owner_id,
                        account_id=c.auth.account_id,
                        run_id=value.run.id,
                        point_id=retained.id,
                        asset_index=j,
                        value=asset.value,
                        created_at=c.now,
                    )
                )
    c.session.flush()
    row.sealed = True
    c.session.flush()
    return row


def store_result(
    value: StoredProjectionFixture,
    calculation: ProjectionCalculation,
    *,
    corrupt_summary: bool = False,
) -> ProjectionResultModel:
    c = value.case
    payload = projection_canonical_bytes(calculation)
    row = ProjectionResultModel(
        id=uuid4(),
        owner_id=c.auth.owner_id,
        account_id=c.auth.account_id,
        run_id=value.run.id,
        job_id=value.job.id,
        lease_token=value.job.lease_token,
        consumer_attempt=value.job.consumer_attempts,
        input_digest=calculation.input_digest,
        content_digest=sha256(payload).hexdigest(),
        byte_length=len(payload),
        canonical_result=payload,
        quality="estimated",
        sampler=calculation.sampler,
        sealed=False,
        created_at=c.now,
    )
    c.session.add(row)
    c.session.flush()
    for index in calculation.numerical_zero_pivots:
        c.session.add(
            ProjectionZeroPivotModel(
                id=uuid4(),
                owner_id=c.auth.owner_id,
                account_id=c.auth.account_id,
                result_id=row.id,
                asset_index=index,
                created_at=c.now,
            )
        )
    for variant in calculation.variants:
        assert variant.goal is None
        for d in variant.distributions:
            summary = ProjectionDistributionModel(
                id=uuid4(),
                owner_id=c.auth.owner_id,
                account_id=c.auth.account_id,
                result_id=row.id,
                variant=variant.variant,
                month=d.month,
                nominal_mean=d.nominal_mean
                + (Decimal(1) if corrupt_summary and d.month == 0 else Decimal(0)),
                real_mean=d.real_mean,
                funding_failed_paths=d.funding_failed_paths,
                created_at=c.now,
            )
            c.session.add(summary)
            c.session.flush()
            for basis in ("nominal", "real"):
                quantiles = getattr(d, basis)
                for probability, amount in zip(
                    quantiles.probabilities, quantiles.values, strict=True
                ):
                    c.session.add(
                        ProjectionDistributionQuantileModel(
                            id=uuid4(),
                            owner_id=c.auth.owner_id,
                            account_id=c.auth.account_id,
                            distribution_id=summary.id,
                            basis=basis,
                            probability=probability,
                            value=amount,
                            created_at=c.now,
                        )
                    )
        for basis in ("nominal", "real"):
            h = getattr(variant, basis + "_histogram")
            histogram = ProjectionHistogramModel(
                id=uuid4(),
                owner_id=c.auth.owner_id,
                account_id=c.auth.account_id,
                result_id=row.id,
                variant=variant.variant,
                basis=basis,
                observed_minimum=h.observed_minimum,
                observed_maximum=h.observed_maximum,
                bin_count=len(h.bins),
                boundary_rule=h.boundary_rule,
                created_at=c.now,
            )
            c.session.add(histogram)
            c.session.flush()
            for i, b in enumerate(h.bins):
                c.session.add(
                    ProjectionHistogramBinModel(
                        id=uuid4(),
                        owner_id=c.auth.owner_id,
                        account_id=c.auth.account_id,
                        histogram_id=histogram.id,
                        bin_index=i,
                        lower=b.lower,
                        upper=b.upper,
                        upper_inclusive=b.upper_inclusive,
                        count=b.count,
                        created_at=c.now,
                    )
                )
    c.session.flush()
    row.sealed = True
    c.session.flush()
    return row


def succeed(value: StoredProjectionFixture) -> None:
    c = value.case
    job = value.job
    job.state = "succeeded"
    job.completed_at = c.now
    job.lease_token = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    job.deadline_at = None
    job.consumer_id = None
    value.outbox.state = "completed"
    c.session.flush()
    retained = c.session.scalar(
        text("SELECT projection_storage_bytes(:run)"), {"run": value.run.id}
    )
    assert isinstance(retained, int) and retained > 0
    value.root.reserved_bytes = 0
    value.root.retained_bytes = retained
    capacity = c.session.get(PremiumCapacityModel, c.auth.owner_id)
    assert capacity is not None
    capacity.active_jobs -= 1
    capacity.reserved_bytes -= 33554432
    capacity.retained_bytes += retained
    finish(c.session)


def test_modeled_capture_is_normalized_and_charged(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    value = queued_projection(projection_definition_case)
    session = value.case.session
    assert (
        session.scalar(text("SELECT projection_capture_complete(:run)"), {"run": value.run.id})
        is True
    )
    assert session.scalar(text("SELECT projection_storage_bytes(:run)"), {"run": value.run.id}) > 0
    assert value.root.reserved_bytes == 33554432


def test_wrong_fence_rejects_checkpoint(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    value = queued_projection(projection_definition_case)
    claim(value)
    chunk = calculate_projection_chunk(value.plan.inputs, 0, 1)
    with pytest.raises(IntegrityError), value.case.session.begin_nested():
        store_chunk(value, chunk, token=uuid4())


@pytest.mark.parametrize("malformed", ("missing_point", "corrupt_money"))
def test_checkpoint_must_match_all_retained_financial_rows(
    projection_definition_case: ProjectionDefinitionCase, malformed: str
) -> None:
    value = queued_projection(projection_definition_case)
    claim(value)
    chunk = calculate_projection_chunk(value.plan.inputs, 0, 1)
    with pytest.raises(IntegrityError), value.case.session.begin_nested():
        store_chunk(
            value,
            chunk,
            missing_point=malformed == "missing_point",
            corrupt_money=malformed == "corrupt_money",
        )
        finish(value.case.session)


def test_overlapping_absolute_checkpoint_paths_are_rejected(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    value = queued_projection(projection_definition_case)
    claim(value)
    chunk = calculate_projection_chunk(value.plan.inputs, 0, 1)
    store_chunk(value, chunk)
    finish(value.case.session)
    with pytest.raises(IntegrityError), value.case.session.begin_nested():
        store_chunk(value, chunk)


def test_success_requires_complete_result(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    value = queued_projection(projection_definition_case)
    claim(value)
    with pytest.raises(IntegrityError), value.case.session.begin_nested():
        succeed(value)


def test_complete_financial_result_matches_saved_chunks_and_summaries(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    value = queued_projection(projection_definition_case)
    claim(value)
    chunk = calculate_projection_chunk(value.plan.inputs, 0, 2)
    store_chunk(value, chunk)
    result = finalize_projection(value.plan.inputs, (chunk,))
    saved = store_result(value, result)
    succeed(value)
    assert saved.canonical_result == projection_canonical_bytes(result)
    assert value.root.retained_bytes > len(saved.canonical_result)
    assert value.job.state == "succeeded"
    with pytest.raises(IntegrityError), value.case.session.begin_nested():
        value.case.session.execute(
            update(ProjectionResultModel)
            .where(ProjectionResultModel.id == saved.id)
            .values(canonical_result=b"")
        )


def test_forged_normalized_result_summary_cannot_succeed(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    value = queued_projection(projection_definition_case)
    claim(value)
    chunk = calculate_projection_chunk(value.plan.inputs, 0, 2)
    store_chunk(value, chunk)
    result = finalize_projection(value.plan.inputs, (chunk,))
    with pytest.raises(IntegrityError), value.case.session.begin_nested():
        store_result(value, result, corrupt_summary=True)
        succeed(value)
