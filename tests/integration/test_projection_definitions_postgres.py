"""Real current grants, immutable normalized versions and semantic retry behavior."""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import Engine, event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import projection as app
from trading212_application.projection_capture import (
    ProjectionDatedSchedule,
    ProjectionGoalVersionContent,
)
from trading212_application.projection_views import ProjectionVersionMetadata
from trading212_domain.projection import ProjectionAsset, ProjectionAssumptions, ProjectionSourcePin
from trading212_domain.sources import SourceUse
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.models import PrincipalModel
from trading212_persistence.premium_models import PremiumAuditModel
from trading212_persistence.projection_definition_store import (
    ProjectionDefinitionStore,
    ProjectionStorageError,
)
from trading212_persistence.projection_models import (
    AssumptionSetModel,
    AssumptionVersionModel,
    GoalVersionModel,
    ProjectionAssumptionAssetModel,
)
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.report_models import (
    ApplicationCommandIdentityModel,
    PrincipalScopeGrantModel,
)
from trading212_security.principals import AuthorizationError, Scope

from tests.integration.test_migrations import _add_identity_graph
from tests.integration.test_migrations import database_engine as database_engine

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def modeled_assumptions() -> ProjectionAssumptions:
    return ProjectionAssumptions(
        assets=(
            ProjectionAsset(
                key="alpha",
                annual_mean_log_return=Decimal(".04"),
                annual_volatility=Decimal(".10"),
                weight=Decimal(".75"),
            ),
            ProjectionAsset(
                key="beta",
                annual_mean_log_return=Decimal(".01"),
                annual_volatility=Decimal(0),
                weight=Decimal(".25"),
            ),
        ),
        correlation=((Decimal(1), Decimal(".2")), (Decimal(".2"), Decimal(1))),
        reporting_currency=CurrencyCode("EUR"),
        annual_inflation=Decimal(".02"),
    )


@dataclass
class ProjectionDefinitionCase:
    session: Session
    store: ProjectionDefinitionStore
    auth: ReportAuthorization
    now: datetime

    def assumption(
        self, *, key: str | None = None, content: ProjectionAssumptions | None = None
    ) -> app.CreateAssumptionSet:
        return app.CreateAssumptionSet(
            account_id=self.auth.account_id,
            metadata=ProjectionVersionMetadata(name="Synthetic assumptions"),
            content=content or modeled_assumptions(),
            idempotency_key=key or str(uuid4()),
            correlation_id="projection-postgres-test",
        )


@pytest.fixture
def projection_definition_case(database_engine: Engine) -> Iterator[ProjectionDefinitionCase]:
    with Session(database_engine) as session:
        owner, _, account, _, _, _ = _add_identity_graph(session)
        now = datetime.now(UTC)
        principal = PrincipalModel(
            id=uuid4(),
            owner_id=owner,
            issuer="https://synthetic.invalid/projections",
            subject=str(uuid4()),
            status="active",
        )
        session.add(principal)
        session.flush()
        scopes = frozenset(
            (Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ, Scope.PROJECTIONS_WRITE, Scope.GOALS_WRITE)
        )
        for scope in scopes:
            session.add(
                PrincipalScopeGrantModel(
                    principal_id=principal.id,
                    scope=scope.value,
                    granted_at=now - timedelta(days=1),
                    expires_at=None,
                    revoked_at=None,
                )
            )
        session.flush()
        auth = ReportAuthorization(
            principal_id=principal.id,
            owner_id=owner,
            account_id=account,
            required_scopes=frozenset(),
            expires_at=now + timedelta(days=1),
            issuer=principal.issuer,
            subject=principal.subject,
        )
        case = ProjectionDefinitionCase(
            session,
            ProjectionDefinitionStore(
                sessionmaker(database_engine),
                cursor_signing_key=b"projection-postgres-key-32-bytes!",
                clock=lambda: now,
            ),
            auth,
            now,
        )
        try:
            yield case
        finally:
            session.rollback()


def finish(session: Session) -> None:
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def test_assumption_exact_round_trip_audit_and_semantic_retry(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    c = projection_definition_case
    request = c.assumption()
    saved = c.store.publish_assumption_set(c.session, c.auth, request)
    version = c.store.read_assumption_version(c.session, c.auth, saved.current_version_id)
    finish(c.session)
    assert version.content == request.content
    assert version.metadata == request.metadata
    retried = c.store.publish_assumption_set(
        c.session, c.auth, replace(request, correlation_id="different-trace")
    )
    assert retried == saved
    assert (
        c.session.scalar(
            select(func.count())
            .select_from(AssumptionVersionModel)
            .where(AssumptionVersionModel.owner_id == c.auth.owner_id)
        )
        == 1
    )
    assert (
        c.session.scalar(
            select(func.count())
            .select_from(PremiumAuditModel)
            .where(PremiumAuditModel.owner_id == c.auth.owner_id)
        )
        == 1
    )
    assert (
        c.session.scalar(
            select(func.count())
            .select_from(ApplicationCommandIdentityModel)
            .where(ApplicationCommandIdentityModel.owner_id == c.auth.owner_id)
        )
        == 1
    )


def test_metadata_change_conflicts_before_new_version(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    c = projection_definition_case
    request = c.assumption()
    c.store.publish_assumption_set(c.session, c.auth, request)
    with pytest.raises(ProjectionStorageError) as conflict:
        c.store.publish_assumption_set(
            c.session,
            c.auth,
            replace(request, metadata=ProjectionVersionMetadata(name="Changed immutable name")),
        )
    assert conflict.value.code is app.ProjectionErrorCode.CONFLICT
    finish(c.session)


def test_revision_successor_is_immutable_and_retry_preserves_original_version(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    c = projection_definition_case
    request = c.assumption()
    head = c.store.publish_assumption_set(c.session, c.auth, request)
    correction = app.CreateAssumptionVersion(
        set_id=head.id,
        expected_revision=1,
        metadata=ProjectionVersionMetadata(name="Corrected model"),
        content=replace(request.content, annual_fee=Decimal(".001")),
        idempotency_key=str(uuid4()),
        correlation_id="version",
    )
    second = c.store.publish_assumption_version(c.session, c.auth, correction)
    finish(c.session)
    assert second.predecessor_id == head.current_version_id and second.version_number == 2
    assert (
        c.store.read_assumption_version(c.session, c.auth, head.current_version_id).content
        == request.content
    )
    assert c.store.publish_assumption_version(c.session, c.auth, correction) == second
    with pytest.raises(ProjectionStorageError) as stale:
        c.store.publish_assumption_version(
            c.session, c.auth, replace(correction, idempotency_key=str(uuid4()))
        )
    assert stale.value.code is app.ProjectionErrorCode.REVISION_MISMATCH
    with pytest.raises(IntegrityError), c.session.begin_nested():
        c.session.execute(
            update(ProjectionAssumptionAssetModel)
            .where(ProjectionAssumptionAssetModel.version_id == second.id)
            .values(annual_mean_log_return=Decimal(".2"))
        )


def test_goal_pins_exact_immutable_assumption_and_schedule(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    c = projection_definition_case
    head = c.store.publish_assumption_set(c.session, c.auth, c.assumption())
    content = ProjectionGoalVersionContent(
        assumption_version_id=head.current_version_id,
        target=Money(Decimal("12345.123456789012345678"), CurrencyCode("EUR")),
        target_date=date(2027, 9, 15),
        months=12,
        basis="real",
        probability_objective=Decimal(".80"),
        schedule=ProjectionDatedSchedule(
            base_monthly=Money(Decimal("123.45"), CurrencyCode("EUR")),
            annual_growth=Decimal(".03"),
            paused_dates=(date(2026, 10, 15),),
        ),
    )
    command = app.CreateGoal(
        account_id=c.auth.account_id,
        metadata=ProjectionVersionMetadata(name="Synthetic goal"),
        content=content,
        idempotency_key=str(uuid4()),
        correlation_id="goal",
    )
    saved = c.store.publish_goal(c.session, c.auth, command)
    assert c.store.read_goal_version(c.session, c.auth, saved.current_version_id).content == content
    changed = app.CreateGoalVersion(
        goal_id=saved.id,
        expected_revision=1,
        metadata=ProjectionVersionMetadata(name="Higher target"),
        content=replace(content, target=Money(Decimal("13000"), CurrencyCode("EUR"))),
        idempotency_key=str(uuid4()),
        correlation_id="goal-2",
    )
    version = c.store.publish_goal_version(c.session, c.auth, changed)
    assert version.predecessor_id == saved.current_version_id
    assert (
        c.store.read_goal_version(c.session, c.auth, saved.current_version_id).content.target
        == content.target
    )
    finish(c.session)


def test_current_grant_revocation_denies_an_idempotent_retry(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    c = projection_definition_case
    request = c.assumption()
    c.store.publish_assumption_set(c.session, c.auth, request)
    grant = c.session.get(
        PrincipalScopeGrantModel, (c.auth.principal_id, Scope.PROJECTIONS_WRITE.value)
    )
    assert grant is not None
    grant.revoked_at = c.now
    c.session.flush()
    with pytest.raises(AuthorizationError):
        c.store.publish_assumption_set(c.session, c.auth, request)


def test_current_source_denial_precedes_any_assumption_financial_select(
    projection_definition_case: ProjectionDefinitionCase, database_engine: Engine
) -> None:
    c = projection_definition_case
    pin = ProjectionSourcePin(subject_id=str(uuid4()), content_digest="a" * 64)
    allowed = [True]

    def resolver(
        session: Session,
        authorization: ReportAuthorization,
        pins: tuple[ProjectionSourcePin, ...],
        *,
        use: SourceUse,
        now: datetime,
    ) -> None:
        assert pins == (pin,) and authorization.account_id == c.auth.account_id
        if not allowed[0]:
            raise ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE)

    c.store._calibration_resolver = resolver
    head = c.store.publish_assumption_set(
        c.session,
        c.auth,
        c.assumption(content=replace(modeled_assumptions(), calibration_pins=(pin,))),
    )
    finish(c.session)
    allowed[0] = False
    statements = []

    def observe(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        many: bool,
    ) -> None:
        statements.append(statement)

    event.listen(database_engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(ProjectionStorageError):
            c.store.read_assumption_version(c.session, c.auth, head.current_version_id)
    finally:
        event.remove(database_engine, "before_cursor_execute", observe)
    assert not any(
        "projection_assumption_assets" in s
        or "projection_correlation_cells" in s
        or "annual_inflation" in s
        for s in statements
    )


def test_restricted_old_source_can_be_removed_by_an_authorized_new_version(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    c = projection_definition_case
    pin = ProjectionSourcePin(subject_id=str(uuid4()), content_digest="b" * 64)
    allowed = [True]

    def resolver(
        session: Session,
        authorization: ReportAuthorization,
        pins: tuple[ProjectionSourcePin, ...],
        *,
        use: SourceUse,
        now: datetime,
    ) -> None:
        if not allowed[0]:
            raise ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE)

    c.store._calibration_resolver = resolver
    head = c.store.publish_assumption_set(
        c.session,
        c.auth,
        c.assumption(content=replace(modeled_assumptions(), calibration_pins=(pin,))),
    )
    allowed[0] = False
    second = c.store.publish_assumption_version(
        c.session,
        c.auth,
        app.CreateAssumptionVersion(
            set_id=head.id,
            expected_revision=1,
            metadata=ProjectionVersionMetadata(name="Owner modeled values"),
            content=modeled_assumptions(),
            idempotency_key=str(uuid4()),
            correlation_id="remove-restricted-pin",
        ),
    )
    assert second.content.calibration_pins == ()
    finish(c.session)


def test_all_definition_families_share_capacity_counter(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    c = projection_definition_case
    capacity = c.store.capacity(c.session, c.auth)
    capacity.definition_versions = 512
    c.session.flush()
    with pytest.raises(ProjectionStorageError) as full:
        c.store.publish_assumption_set(c.session, c.auth, c.assumption())
    assert full.value.code is app.ProjectionErrorCode.RATE_LIMITED


def test_unpublished_head_revision_cannot_commit(
    projection_definition_case: ProjectionDefinitionCase,
) -> None:
    c = projection_definition_case
    head = c.store.publish_assumption_set(c.session, c.auth, c.assumption())
    finish(c.session)
    with pytest.raises(IntegrityError), c.session.begin_nested():
        c.session.execute(
            update(AssumptionSetModel)
            .where(AssumptionSetModel.id == head.id)
            .values(revision=2, updated_at=c.now)
        )
        finish(c.session)


def test_cross_account_goal_version_is_rejected_before_goal_content(
    projection_definition_case: ProjectionDefinitionCase, database_engine: Engine
) -> None:
    c = projection_definition_case
    head = c.store.publish_assumption_set(c.session, c.auth, c.assumption())
    _, _, other_account, _, _, _ = _add_identity_graph(c.session)
    content = ProjectionGoalVersionContent(
        assumption_version_id=head.current_version_id,
        target=Money(Decimal(1), CurrencyCode("EUR")),
        target_date=date(2027, 9, 15),
        months=12,
        basis="nominal",
        probability_objective=Decimal(".5"),
        schedule=ProjectionDatedSchedule(base_monthly=Money(Decimal(0), CurrencyCode("EUR"))),
    )
    command = app.CreateGoal(
        account_id=other_account,
        metadata=ProjectionVersionMetadata(name="Foreign account"),
        content=content,
        idempotency_key=str(uuid4()),
        correlation_id="foreign",
    )
    with pytest.raises(ProjectionStorageError) as denied:
        c.store.publish_goal(c.session, c.auth, command)
    assert denied.value.code is app.ProjectionErrorCode.NOT_FOUND
    assert (
        c.session.scalar(
            select(func.count())
            .select_from(GoalVersionModel)
            .where(GoalVersionModel.owner_id == c.auth.owner_id)
        )
        == 0
    )
