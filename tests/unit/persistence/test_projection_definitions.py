"""Semantic definition identity and authority-before-content regressions."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Context, Decimal, Inexact, localcontext
from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import projection as app
from trading212_application.projection_capture import (
    ProjectionDatedEntry,
    ProjectionDatedSchedule,
    ProjectionGoalVersionContent,
    projection_definition_digest,
)
from trading212_application.projection_views import ProjectionVersionMetadata
from trading212_domain.projection import ProjectionAsset, ProjectionAssumptions, ProjectionSourcePin
from trading212_domain.sources import SourceUse
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.projection_definition_store import (
    ProjectionDefinitionStore,
    ProjectionStorageError,
    projection_definition_command_digest,
)
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_security.principals import AuthorizationError, Scope

AT = datetime(2026, 9, 15, 12, tzinfo=UTC)
ACCOUNT = UUID(int=2)


def assumptions() -> ProjectionAssumptions:
    return ProjectionAssumptions(
        assets=(
            ProjectionAsset(
                key="alpha",
                annual_mean_log_return=Decimal(".04"),
                annual_volatility=Decimal(".1"),
                weight=Decimal(".6"),
            ),
            ProjectionAsset(
                key="beta",
                annual_mean_log_return=Decimal(".02"),
                annual_volatility=Decimal(".05"),
                weight=Decimal(".4"),
            ),
        ),
        correlation=((Decimal(1), Decimal(".25")), (Decimal(".25"), Decimal(1))),
        reporting_currency=CurrencyCode("EUR"),
    )


def authorization() -> ReportAuthorization:
    return ReportAuthorization(
        principal_id=UUID(int=3),
        owner_id=UUID(int=1),
        account_id=ACCOUNT,
        required_scopes=frozenset((Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ)),
        expires_at=AT + timedelta(days=1),
        issuer="synthetic",
        subject="projection-test",
    )


def test_metadata_is_semantic_without_changing_numerical_definition_digest() -> None:
    value = assumptions()
    metadata = ProjectionVersionMetadata(name="Baseline")
    original = projection_definition_command_digest(
        "projection.assumption.create.v1", ACCOUNT, metadata, value
    )
    renamed = projection_definition_command_digest(
        "projection.assumption.create.v1", ACCOUNT, replace(metadata, name="Renamed"), value
    )
    described = projection_definition_command_digest(
        "projection.assumption.create.v1",
        ACCOUNT,
        replace(metadata, description="A material immutable note"),
        value,
    )
    assert len({original, renamed, described}) == 3
    assert projection_definition_digest(value) == projection_definition_digest(replace(value))


def test_version_command_binds_revision_aggregate_and_account() -> None:
    value = assumptions()
    metadata = ProjectionVersionMetadata(name="Baseline")

    aggregate_id = UUID(int=10)

    def digest(
        *, account: UUID = ACCOUNT, aggregate: UUID = aggregate_id, revision: int = 1
    ) -> str:
        return projection_definition_command_digest(
            "projection.assumption.version.create.v1",
            account,
            metadata,
            value,
            aggregate_id=aggregate,
            expected_revision=revision,
        )

    assert (
        len(
            {
                digest(),
                digest(account=UUID(int=20)),
                digest(aggregate=UUID(int=11)),
                digest(revision=2),
            }
        )
        == 4
    )


def test_canonical_asset_reordering_is_one_semantic_request() -> None:
    value = assumptions()
    metadata = ProjectionVersionMetadata(name="Baseline")
    reordered = replace(
        value,
        assets=tuple(reversed(value.assets)),
        correlation=((Decimal(1), Decimal(".25")), (Decimal(".25"), Decimal(1))),
    )
    assert projection_definition_command_digest(
        "projection.assumption.create.v1", ACCOUNT, metadata, value
    ) == projection_definition_command_digest(
        "projection.assumption.create.v1", ACCOUNT, metadata, reordered
    )


def test_goal_schedule_identity_is_bound_even_when_total_amount_is_unchanged() -> None:
    schedule = ProjectionDatedSchedule(
        base_monthly=Money(Decimal(1), CurrencyCode("EUR")),
        entries=(
            ProjectionDatedEntry(
                key="lump-a",
                on=date(2026, 9, 15),
                kind="lump_sum",
                value=Money(Decimal(10), CurrencyCode("EUR")),
            ),
        ),
    )
    content = ProjectionGoalVersionContent(
        assumption_version_id=UUID(int=1),
        target=Money(Decimal(100), CurrencyCode("EUR")),
        target_date=date(2027, 9, 15),
        months=12,
        basis="real",
        probability_objective=Decimal(".75"),
        schedule=schedule,
    )
    renamed = replace(
        content, schedule=replace(schedule, entries=(replace(schedule.entries[0], key="lump-b"),))
    )
    metadata = ProjectionVersionMetadata(name="Goal")
    assert projection_definition_command_digest(
        "projection.goal.create.v1", ACCOUNT, metadata, content
    ) != projection_definition_command_digest(
        "projection.goal.create.v1", ACCOUNT, metadata, renamed
    )


def test_digest_is_independent_of_hostile_decimal_context() -> None:
    value = assumptions()
    metadata = ProjectionVersionMetadata(name="Baseline")
    expected = projection_definition_command_digest(
        "projection.assumption.create.v1", ACCOUNT, metadata, value
    )
    hostile = Context(prec=2, rounding=ROUND_DOWN, Emin=-2, Emax=2)
    hostile.traps[Inexact] = True
    with localcontext(hostile):
        assert (
            projection_definition_command_digest(
                "projection.assumption.create.v1", ACCOUNT, metadata, value
            )
            == expected
        )


@pytest.mark.parametrize(
    ("kind", "scope"),
    (
        ("assumption", Scope.PROJECTIONS_WRITE),
        ("goal", Scope.GOALS_WRITE),
        ("run", Scope.PROJECTIONS_WRITE),
    ),
)
def test_current_write_scope_precedes_any_private_statement(
    monkeypatch: pytest.MonkeyPatch, kind: str, scope: Scope
) -> None:
    store = ProjectionDefinitionStore(
        sessionmaker(), cursor_signing_key=b"projection-unit-key-32-bytes-long!", clock=lambda: AT
    )
    session = Mock(spec=Session)

    def deny(self: ReportAuthorization, session: Session, *, now: datetime) -> None:
        assert scope in self.required_scopes
        raise AuthorizationError("access denied")

    monkeypatch.setattr(ReportAuthorization, "check", deny)
    with pytest.raises(AuthorizationError):
        store.authority(session, authorization(), write=kind)  # type: ignore[arg-type]
    session.execute.assert_not_called()
    session.scalar.assert_not_called()


def test_nonempty_calibration_pins_require_explicit_server_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ReportAuthorization, "check", lambda *args, **kwargs: None)
    store = ProjectionDefinitionStore(
        sessionmaker(), cursor_signing_key=b"projection-unit-key-32-bytes-long!", clock=lambda: AT
    )
    pin = ProjectionSourcePin(subject_id=str(UUID(int=99)), content_digest="a" * 64)
    session = Mock(spec=Session)
    with pytest.raises(ProjectionStorageError) as denied:
        store._permit(session, authorization(), (pin,))
    assert denied.value.code is app.ProjectionErrorCode.SOURCE_UNAVAILABLE
    session.execute.assert_not_called()
    store._permit(session, authorization(), ())


def test_resolver_receives_exact_pins_and_current_store_display_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ReportAuthorization, "check", lambda *args, **kwargs: None)
    calls = []

    def resolve(
        session: Session,
        authorization: ReportAuthorization,
        pins: tuple[ProjectionSourcePin, ...],
        *,
        use: SourceUse,
        now: datetime,
    ) -> None:
        calls.append((authorization.account_id, pins, use, now))

    store = ProjectionDefinitionStore(
        sessionmaker(),
        cursor_signing_key=b"projection-unit-key-32-bytes-long!",
        clock=lambda: AT,
        calibration_resolver=resolve,
    )
    pin = ProjectionSourcePin(subject_id=str(UUID(int=99)), content_digest="a" * 64)
    store._permit(Mock(spec=Session), authorization(), (pin,))
    assert calls == [
        (ACCOUNT, (pin,), SourceUse.STORE, AT),
        (ACCOUNT, (pin,), SourceUse.DISPLAY, AT),
    ]
