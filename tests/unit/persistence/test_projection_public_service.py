"""Public account pin and source checks precede retained finance and cursor decoding."""

from collections.abc import Callable
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import projection as app
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.projection_service import PostgresProjectionService
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_security.principals import AuthorizationError, Principal, Scope

from tests.unit.persistence.projection_result_store_factories import AT, records


def principal() -> Principal:
    _, _, auth, _, _, _ = records()
    return Principal(
        str(auth.principal_id),
        str(auth.owner_id),
        auth.issuer,
        auth.subject,
        frozenset(Scope),
        AT - timedelta(minutes=1),
        AT + timedelta(days=1),
    )


def service() -> tuple[PostgresProjectionService, MagicMock]:
    session = MagicMock(spec=Session)
    sessions = MagicMock()
    sessions.return_value.__enter__.return_value = session
    return PostgresProjectionService(
        cast(sessionmaker[Session], sessions),
        cursor_signing_key=b"synthetic-public-projection" * 2,
        clock=lambda: AT,
    ), session


def inline(session: Session, auth: ReportAuthorization) -> AsyncMock:
    async def run[T](
        _principal: Principal,
        _account: UUID | None,
        operation: Callable[[Session, ReportAuthorization], T],
        **_options: object,
    ) -> T:
        return operation(session, auth)

    return AsyncMock(side_effect=run)


async def test_explicit_account_pin_rejects_before_durable_lookup_or_cursor() -> None:
    value, session = service()
    _, _, _, root, _, _ = records()
    session.scalar.return_value = root.account_id
    with (
        patch(
            "trading212_persistence.projection_service_base.authorize_report_request"
        ) as authorize,
        patch.object(value, "_run_rows") as rows,
        patch("trading212_persistence.projection_service.project_saved_projection_page") as page,
        pytest.raises(app.ProjectionServiceError) as denied,
    ):
        await value.get_run(
            principal(),
            root.id,
            app.ProjectionPointPageQuery(point_cursor="private-cursor-canary"),
            expected_account_id=UUID(int=90001),
        )
    assert denied.value.code is app.ProjectionErrorCode.NOT_FOUND
    authorize.assert_not_called()
    rows.assert_not_called()
    page.assert_not_called()


async def test_revoked_current_grant_precedes_private_projection_and_cursor() -> None:
    value, session = service()
    _, _, _, root, _, _ = records()
    session.scalar.return_value = root.account_id
    with (
        patch(
            "trading212_persistence.projection_service_base.authorize_report_request",
            side_effect=AuthorizationError("private-grant-canary"),
        ),
        patch.object(value, "_run_rows") as rows,
        patch("trading212_persistence.projection_service.project_saved_projection_page") as page,
        pytest.raises(app.ProjectionServiceError) as denied,
    ):
        await value.get_run(
            principal(),
            root.id,
            app.ProjectionPointPageQuery(point_cursor="private-cursor-canary"),
        )
    assert denied.value.code is app.ProjectionErrorCode.ACCESS_DENIED
    assert "canary" not in str(denied.value)
    rows.assert_not_called()
    page.assert_not_called()


async def test_original_source_denial_precedes_input_result_and_cursor() -> None:
    value, session = service()
    _, _, auth, root, run, job = records()
    job.state, job.completed_at = "succeeded", AT
    with (
        patch.object(value, "_execute", inline(session, auth)),
        patch.object(value, "_run_rows", return_value=(root, run, job)),
        patch.object(value, "_restricted", return_value=False),
        patch(
            "trading212_persistence.projection_service.require_projection_run_sources",
            side_effect=ProjectionStorageError(app.ProjectionErrorCode.SOURCE_UNAVAILABLE),
        ),
        patch.object(value, "read_retained_input") as inputs,
        patch.object(value, "read_result") as result,
        patch("trading212_persistence.projection_service.project_saved_projection_page") as page,
        pytest.raises(ProjectionStorageError),
    ):
        await value.get_run(
            principal(),
            root.id,
            app.ProjectionPointPageQuery(point_cursor="private-cursor-canary"),
        )
    inputs.assert_not_called()
    result.assert_not_called()
    page.assert_not_called()


async def test_expired_success_is_operational_without_private_input_reads() -> None:
    value, session = service()
    _, _, auth, root, run, job = records()
    job.state, job.completed_at = "succeeded", AT
    with (
        patch.object(value, "_execute", inline(session, auth)),
        patch.object(value, "_run_rows", return_value=(root, run, job)),
        patch.object(value, "_restricted", return_value=True),
        patch.object(value, "_retained") as retained,
    ):
        saved = await value.get_run(principal(), root.id, app.ProjectionPointPageQuery())
        with pytest.raises(app.ProjectionServiceError) as cursor:
            await value.get_run(
                principal(), root.id, app.ProjectionPointPageQuery(point_cursor="obsolete-cursor")
            )
    assert saved.result is None and saved.result_availability == "expired"
    assert saved.capture_digest == root.input_digest
    assert cursor.value.code is app.ProjectionErrorCode.RUN_EXPIRED
    retained.assert_not_called()


async def test_goal_free_pending_read_requires_current_sources_but_no_financial_decode() -> None:
    value, session = service()
    _, _, auth, root, run, job = records()
    run.goal_version_id = run.goal_digest = None
    job.state = "queued"
    with (
        patch.object(value, "_execute", inline(session, auth)),
        patch.object(value, "_run_rows", return_value=(root, run, job)),
        patch.object(value, "_restricted", return_value=False),
        patch(
            "trading212_persistence.projection_service.require_projection_run_sources"
        ) as sources,
        patch.object(value, "_retained") as retained,
    ):
        goal = await value.get_goal_analysis(principal(), root.id)
    assert goal.availability == "unavailable" and goal.reason == "no_goal_pinned"
    assert goal.context is None and goal.variants == ()
    sources.assert_called_once_with(value, session, auth, root, run)
    retained.assert_not_called()
