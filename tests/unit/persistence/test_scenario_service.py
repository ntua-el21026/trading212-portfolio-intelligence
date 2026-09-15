"""Scenario transaction denial, semantic retry identity and terminal byte accounting."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import scenario as app
from trading212_domain import CurrencyCode
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRunModel,
)
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.scenario_service import (
    PostgresScenarioService,
    scenario_run_command_digest,
)
from trading212_persistence.scenario_store_types import (
    ScenarioStorageError,
    ScenarioStorageErrorCode,
)
from trading212_security.principals import AuthorizationError, Principal, Scope

AT = datetime(2026, 8, 31, 12, tzinfo=UTC)
OWNER = UUID("00000000-0000-0000-0000-000000000101")
ACCOUNT = UUID("00000000-0000-0000-0000-000000000102")
IDENTITY = UUID("00000000-0000-0000-0000-000000000103")
PRINCIPAL = Principal(
    str(IDENTITY),
    str(OWNER),
    "synthetic.issuer",
    "scenario-reader",
    frozenset(Scope),
    AT - timedelta(minutes=1),
    AT + timedelta(days=1),
)
AUTH = ReportAuthorization(
    principal_id=IDENTITY,
    owner_id=OWNER,
    account_id=ACCOUNT,
    required_scopes=frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ}),
    expires_at=PRINCIPAL.expires_at,
    issuer=PRINCIPAL.issuer,
    subject=PRINCIPAL.subject,
    requesting_principal=PRINCIPAL,
)


def service() -> tuple[PostgresScenarioService, MagicMock, MagicMock]:
    session = MagicMock(spec=Session)
    session.__enter__.return_value = session
    sessions = MagicMock(return_value=session)
    return (
        PostgresScenarioService(
            cast(sessionmaker[Session], sessions),
            cursor_signing_key=b"synthetic-cursor-key" * 2,
            clock=lambda: AT,
        ),
        sessions,
        session,
    )


def command() -> app.CreateScenarioRun:
    return app.CreateScenarioRun(
        account_id=ACCOUNT,
        scenario_version_id=uuid4(),
        portfolio_snapshot_id=uuid4(),
        xray_run_id=uuid4(),
        reporting_currency=CurrencyCode("EUR"),
        source_cutoff_at=AT,
        idempotency_key="synthetic-run-key",
        correlation_id="trace-one",
    )


def test_run_digest_binds_requested_material_identities_and_ignores_retry_trace() -> None:
    value = command()
    digest = scenario_run_command_digest(value)
    assert digest == scenario_run_command_digest(
        replace(value, idempotency_key="another-retry-key", correlation_id="trace-two")
    )
    for candidate in (
        replace(value, account_id=uuid4()),
        replace(value, scenario_version_id=uuid4()),
        replace(value, portfolio_snapshot_id=uuid4()),
        replace(value, xray_run_id=uuid4()),
        replace(value, reporting_currency=CurrencyCode("USD")),
        replace(value, source_cutoff_at=AT - timedelta(seconds=1)),
    ):
        assert scenario_run_command_digest(candidate) != digest


@pytest.mark.parametrize("write", [False, True])
async def test_missing_token_scope_never_opens_database(write: bool) -> None:
    store, sessions, _ = service()
    principal = replace(PRINCIPAL, scopes=frozenset({Scope.PORTFOLIO_READ}))
    operation = MagicMock()
    with pytest.raises(app.ScenarioServiceError) as denied:
        await store._execute(principal, ACCOUNT, operation, write=write)
    assert denied.value.code is app.ScenarioErrorCode.ACCESS_DENIED
    sessions.assert_not_called()
    operation.assert_not_called()


async def test_revoked_durable_grant_precedes_operation_and_cursor() -> None:
    store, _, _ = service()
    operation = MagicMock(side_effect=AssertionError("private read before current grant"))
    with (
        patch(
            "trading212_persistence.scenario_service_base.authorize_report_request",
            side_effect=AuthorizationError("synthetic-private-canary"),
        ),
        patch.object(
            store._cursors, "decode", side_effect=AssertionError("cursor before grant")
        ) as decode,
        pytest.raises(app.ScenarioServiceError) as denied,
    ):
        await store._execute(PRINCIPAL, ACCOUNT, operation)
    assert denied.value.code is app.ScenarioErrorCode.ACCESS_DENIED
    assert "synthetic-private-canary" not in str(denied.value)
    operation.assert_not_called()
    decode.assert_not_called()


async def test_requested_account_mismatch_precedes_private_rows_and_cursor() -> None:
    store, _, session = service()
    session.scalar.return_value = ACCOUNT
    with (
        patch(
            "trading212_persistence.scenario_service_base.authorize_report_request",
            return_value=AUTH,
        ),
        patch("trading212_persistence.scenario_service_base.scenario_owner_lock"),
        patch.object(ReportAuthorization, "check"),
        patch.object(store, "_run_rows", side_effect=AssertionError("private rows")) as rows,
        patch.object(store._cursors, "decode", side_effect=AssertionError("cursor")) as decode,
        pytest.raises(app.ScenarioServiceError) as rejected,
    ):
        await store.get_run(
            PRINCIPAL,
            uuid4(),
            app.ScenarioComponentPageQuery(component_cursor="malformed"),
            expected_account_id=uuid4(),
        )
    assert rejected.value.code is app.ScenarioErrorCode.NOT_FOUND
    rows.assert_not_called()
    decode.assert_not_called()


async def test_invalid_requested_account_rejected_before_database() -> None:
    store, sessions, _ = service()
    with pytest.raises(app.ScenarioServiceError) as rejected:
        await store.get_run(
            PRINCIPAL,
            uuid4(),
            app.ScenarioComponentPageQuery(),
            expected_account_id=cast(UUID, "private-invalid-account-canary"),
        )
    assert rejected.value.code is app.ScenarioErrorCode.VALIDATION_FAILED
    assert "canary" not in str(rejected.value)
    sessions.assert_not_called()


async def test_expiry_after_processing_rolls_back_instead_of_returning_result() -> None:
    store, _, session = service()
    operation = MagicMock(return_value="private result")
    with (
        patch(
            "trading212_persistence.scenario_service_base.authorize_report_request",
            return_value=AUTH,
        ),
        patch("trading212_persistence.scenario_service_base.scenario_owner_lock"),
        patch.object(
            ReportAuthorization, "check", side_effect=[None, AuthorizationError("expired")]
        ),
        pytest.raises(app.ScenarioServiceError) as expired,
    ):
        await store._execute(PRINCIPAL, ACCOUNT, operation)
    assert expired.value.code is app.ScenarioErrorCode.ACCESS_DENIED
    operation.assert_called_once()
    assert session.begin.return_value.__exit__.call_args.args[0] is AuthorizationError


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            ScenarioStorageError(ScenarioStorageErrorCode.SOURCE_UNAVAILABLE),
            app.ScenarioErrorCode.SOURCE_UNAVAILABLE,
        ),
        (
            IntegrityError("private-sql-canary", {}, RuntimeError("private-parameter-canary")),
            app.ScenarioErrorCode.CONFLICT,
        ),
        (SQLAlchemyError("private-sql-canary"), app.ScenarioErrorCode.SCENARIO_UNAVAILABLE),
    ],
)
async def test_storage_failures_are_fixed_and_unchained(
    failure: Exception,
    expected: app.ScenarioErrorCode,
) -> None:
    store, _, _ = service()
    with (
        patch(
            "trading212_persistence.scenario_service_base.authorize_report_request",
            return_value=AUTH,
        ),
        patch("trading212_persistence.scenario_service_base.scenario_owner_lock"),
        patch.object(ReportAuthorization, "check"),
        pytest.raises(app.ScenarioServiceError) as rejected,
    ):
        await store._execute(PRINCIPAL, ACCOUNT, MagicMock(side_effect=failure))
    assert rejected.value.code is expected
    assert str(rejected.value) == "The scenario operation cannot be completed."
    assert rejected.value.__cause__ is None and rejected.value.__context__ is None


@pytest.mark.parametrize("state", ["cancelled", "failed", "expired"])
def test_terminal_failure_retains_actual_input_bytes_and_releases_capacity_once(state: str) -> None:
    store, _, raw_session = service()
    session = cast(Session, raw_session)
    root = PremiumRunModel(
        id=uuid4(),
        owner_id=OWNER,
        account_id=ACCOUNT,
        kind="scenario",
        reserved_bytes=33554432,
        retained_bytes=0,
    )
    job = PremiumJobModel(
        id=uuid4(),
        owner_id=OWNER,
        account_id=ACCOUNT,
        run_id=root.id,
        state="queued",
        consumer_attempts=0,
    )
    capacity = PremiumCapacityModel(
        owner_id=OWNER,
        active_jobs=2,
        reserved_bytes=67108864,
        retained_bytes=100,
        definition_versions=1,
    )
    outbox = PremiumOutboxModel(
        owner_id=OWNER,
        account_id=ACCOUNT,
        job_id=job.id,
        state="pending",
    )
    raw_session.scalar.return_value = outbox
    with (
        patch.object(store, "_result_bytes", return_value=250),
        patch.object(store, "_capacity_for_owner", return_value=capacity),
        patch("trading212_persistence.scenario_service.premium_attempt") as attempt,
    ):
        store._finish_job(session, root, job, state, None)
        assert root.reserved_bytes == 0 and root.retained_bytes == 250
        assert capacity.active_jobs == 1 and capacity.reserved_bytes == 33554432
        assert capacity.retained_bytes == 350
        assert job.state == state and job.completed_at == AT
        assert outbox.state == ("completed" if state == "cancelled" else "dead_letter")
        with pytest.raises(app.ScenarioServiceError) as terminal:
            store._finish_job(session, root, job, state, None)
        assert terminal.value.code is app.ScenarioErrorCode.INVALID_STATE_TRANSITION
        assert capacity.active_jobs == 1 and capacity.retained_bytes == 350
        attempt.assert_called_once()


def test_succeeded_completion_rejects_unaccounted_retained_bytes() -> None:
    store, _, raw_session = service()
    root = PremiumRunModel(
        id=uuid4(),
        owner_id=OWNER,
        account_id=ACCOUNT,
        kind="scenario",
        reserved_bytes=33554432,
        retained_bytes=0,
    )
    job = PremiumJobModel(
        id=uuid4(),
        owner_id=OWNER,
        account_id=ACCOUNT,
        run_id=root.id,
        state="running",
        consumer_attempts=1,
    )
    with (
        patch.object(store, "_result_bytes", return_value=999),
        patch.object(store, "_capacity_for_owner") as capacity,
        pytest.raises(app.ScenarioServiceError) as mismatch,
    ):
        store._finish_job(
            cast(Session, raw_session), root, job, "succeeded", None, retained_bytes=998
        )
    assert mismatch.value.code is app.ScenarioErrorCode.SCENARIO_UNAVAILABLE
    assert root.reserved_bytes == 33554432 and job.state == "running"
    capacity.assert_not_called()
