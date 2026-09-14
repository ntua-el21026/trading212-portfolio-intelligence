"""Real PostgreSQL constraints for risk publication and bounded premium authority.

The unpublished job fixtures deliberately roll back: they test admission constraints,
not successful canonical financial execution (covered by subsequent service tests).
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from trading212_persistence.models import OwnerModel, PrincipalModel
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumRunModel,
)
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    PrincipalScopeGrantModel,
)
from trading212_persistence.risk_models import RiskDefinitionModel, RiskVersionModel
from trading212_persistence.source_models import SourceCalendarModel

from tests.integration.test_migrations import _add_identity_graph
from tests.integration.test_migrations import database_engine as database_engine

pytestmark = [pytest.mark.integration, pytest.mark.migrations]
NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
D = Decimal


@pytest.fixture
def scope(database_engine: Engine) -> Iterator[tuple[Session, UUID, UUID, UUID, UUID]]:
    with Session(database_engine) as session:
        owner, _, account, _, _, _ = _add_identity_graph(session)
        principal, calendar = uuid4(), uuid4()
        session.add_all(
            (
                PrincipalModel(
                    id=principal,
                    owner_id=owner,
                    issuer="https://synthetic.invalid/risk",
                    subject=str(principal),
                    status="active",
                ),
                SourceCalendarModel(
                    id=calendar,
                    owner_id=owner,
                    key="risk-calendar",
                    version="1",
                    timezone="UTC",
                    period_start=NOW.date(),
                    period_end=NOW.date(),
                    content_digest="a" * 64,
                ),
                PremiumCapacityModel(
                    owner_id=owner,
                    reserved_bytes=0,
                    retained_bytes=0,
                    active_jobs=0,
                    definition_versions=1,
                    updated_at=NOW,
                ),
            )
        )
        session.flush()
        try:
            yield session, owner, account, principal, calendar
        finally:
            session.rollback()


def version(
    session: Session, owner: UUID, account: UUID, calendar: UUID
) -> tuple[RiskDefinitionModel, RiskVersionModel]:
    definition = RiskDefinitionModel(
        id=uuid4(),
        owner_id=owner,
        account_id=account,
        name="Risk",
        revision=1,
        archived=False,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(definition)
    session.flush()
    row = RiskVersionModel(
        id=uuid4(),
        owner_id=owner,
        account_id=account,
        definition_id=definition.id,
        version_number=1,
        predecessor_id=None,
        calendar_id=calendar,
        name="Risk",
        description="Synthetic",
        frequency="daily",
        return_kind="simple",
        annual_risk_free=D(".012345678901234567"),
        annual_minimum_acceptable_return=D(0),
        rolling_window=20,
        confidence=D(".95"),
        horizon=1,
        regularization="none",
        shrinkage=D(0),
        method_version="1.0.0",
        content_digest="b" * 64,
        created_at=NOW,
    )
    session.add(row)
    session.flush()
    return definition, row


def run_prefix(session: Session, owner: UUID, account: UUID, principal: UUID) -> UUID:
    """An unpublished prefix to test immediate job constraints; never committed."""
    run_id, command_id = uuid4(), uuid4()
    session.add(
        ApplicationCommandIdentityModel(
            id=command_id,
            owner_id=owner,
            account_id=account,
            command="risk.run.create.v1",
            idempotency_key=str(command_id),
            command_digest="c" * 64,
            premium_resource_id=run_id,
            premium_actor_id=principal,
            premium_correlation_id="schema",
            report_job_id=None,
            export_job_id=None,
            created_at=NOW,
        )
    )
    session.flush()
    session.add(
        PremiumRunModel(
            id=run_id,
            owner_id=owner,
            account_id=account,
            kind="risk",
            command_id=command_id,
            actor_principal_id=principal,
            input_digest="d" * 64,
            expires_at=NOW + timedelta(days=1),
            method_version="1.0.0",
            schema_version="1.0.0",
            numerical_profile="premium_decimal96_q18_v1",
            reserved_bytes=33554432,
            retained_bytes=0,
            created_at=NOW,
        )
    )
    session.flush()
    return run_id


def test_risk_version_is_exact_and_new_grants_are_registered(
    scope: tuple[Session, UUID, UUID, UUID, UUID],
) -> None:
    session, owner, account, principal, calendar = scope
    _, row = version(session, owner, account, calendar)
    session.add(
        PrincipalScopeGrantModel(principal_id=principal, scope="risk:write", granted_at=NOW)
    )
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.expire(row)
    assert row.annual_risk_free == D(".012345678901234567")
    assert row.confidence == D(".95") and row.created_at.tzinfo is not None


def test_risk_definition_cannot_reference_another_owners_account(
    scope: tuple[Session, UUID, UUID, UUID, UUID],
) -> None:
    session, _, account, _, _ = scope
    other = uuid4()
    session.add(OwnerModel(id=other, display_name="Other synthetic owner"))
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            RiskDefinitionModel(
                id=uuid4(),
                owner_id=other,
                account_id=account,
                name="Forbidden",
                revision=1,
                archived=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()


def test_version_and_aggregate_publication_cannot_be_changed_in_place(
    scope: tuple[Session, UUID, UUID, UUID, UUID],
) -> None:
    session, owner, account, _, calendar = scope
    definition, row = version(session, owner, account, calendar)
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            update(RiskVersionModel).where(RiskVersionModel.id == row.id).values(name="Changed")
        )
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            update(RiskDefinitionModel)
            .where(RiskDefinitionModel.id == definition.id)
            .values(name="Changed")
        )
    with pytest.raises(IntegrityError), session.begin_nested():
        session.delete(row)
        session.flush()


def test_definition_without_immutable_version_fails_deferred_publication(
    scope: tuple[Session, UUID, UUID, UUID, UUID],
) -> None:
    session, owner, account, _, _ = scope
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            RiskDefinitionModel(
                id=uuid4(),
                owner_id=owner,
                account_id=account,
                name="Incomplete",
                revision=1,
                archived=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_command_target_is_bound_to_owner_and_account(
    scope: tuple[Session, UUID, UUID, UUID, UUID],
) -> None:
    session, owner, account, principal, calendar = scope
    version(session, owner, account, calendar)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            ApplicationCommandIdentityModel(
                id=uuid4(),
                owner_id=owner,
                account_id=account,
                command="risk.definition.create.v1",
                idempotency_key="missing-target",
                command_digest="c" * 64,
                premium_resource_id=uuid4(),
                premium_actor_id=principal,
                premium_correlation_id="schema",
                report_job_id=None,
                export_job_id=None,
                created_at=NOW,
            )
        )
        session.flush()
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.parametrize(
    "field,value", (("reserved_bytes", 268435457), ("active_jobs", 3), ("definition_versions", 513))
)
def test_shared_owner_capacity_has_database_limits(
    scope: tuple[Session, UUID, UUID, UUID, UUID], field: str, value: int
) -> None:
    session, owner, _, _, _ = scope
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            update(PremiumCapacityModel)
            .where(PremiumCapacityModel.owner_id == owner)
            .values(**{field: value})
        )


def test_queued_job_cannot_have_a_partial_lease(
    scope: tuple[Session, UUID, UUID, UUID, UUID],
) -> None:
    session, owner, account, principal, _ = scope
    run_id = run_prefix(session, owner, account, principal)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            PremiumJobModel(
                id=uuid4(),
                owner_id=owner,
                account_id=account,
                run_id=run_id,
                state="queued",
                consumer_attempts=0,
                lease_token=uuid4(),
                created_at=NOW,
            )
        )
        session.flush()


def test_only_one_premium_job_can_run_even_for_distinct_owners(
    scope: tuple[Session, UUID, UUID, UUID, UUID],
) -> None:
    session, owner, account, principal, _ = scope
    first = run_prefix(session, owner, account, principal)
    session.add(
        PremiumJobModel(
            id=uuid4(),
            owner_id=owner,
            account_id=account,
            run_id=first,
            state="running",
            consumer_attempts=1,
            lease_token=uuid4(),
            lease_expires_at=NOW + timedelta(seconds=60),
            heartbeat_at=NOW,
            deadline_at=NOW + timedelta(seconds=240),
            consumer_id="first",
            created_at=NOW,
        )
    )
    session.flush()
    second_owner, _, second_account, _, _, _ = _add_identity_graph(session)
    second_principal = uuid4()
    session.add(
        PrincipalModel(
            id=second_principal,
            owner_id=second_owner,
            issuer="https://synthetic.invalid/risk",
            subject=str(second_principal),
            status="active",
        )
    )
    session.add(
        PremiumCapacityModel(
            owner_id=second_owner,
            reserved_bytes=0,
            retained_bytes=0,
            active_jobs=0,
            definition_versions=0,
            updated_at=NOW,
        )
    )
    session.flush()
    second = run_prefix(session, second_owner, second_account, second_principal)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            PremiumJobModel(
                id=uuid4(),
                owner_id=second_owner,
                account_id=second_account,
                run_id=second,
                state="running",
                consumer_attempts=1,
                lease_token=uuid4(),
                lease_expires_at=NOW + timedelta(seconds=60),
                heartbeat_at=NOW,
                deadline_at=NOW + timedelta(seconds=240),
                consumer_id="second",
                created_at=NOW,
            )
        )
        session.flush()
    assert (
        session.scalar(select(PremiumJobModel.id).where(PremiumJobModel.run_id == first))
        is not None
    )


def test_unpublished_prefix_cannot_commit_as_complete_work(
    scope: tuple[Session, UUID, UUID, UUID, UUID],
) -> None:
    session, owner, account, principal, _ = scope
    with pytest.raises(IntegrityError), session.begin_nested():
        run_prefix(session, owner, account, principal)
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
