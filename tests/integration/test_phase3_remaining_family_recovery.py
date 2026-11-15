"""Queued risk/scenario recovery after real dependency loss and an empty restore.

The pre-existing fixture clocks define source knowledge and license semantics.
All outage/restore/recovery durations use the real monotonic clock. This adds
neither a production RTO claim nor another all-nine-service restart assertion.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_analytics.risk import calculate_risk
from trading212_analytics.risk_history import validate_risk_capacity
from trading212_analytics.scenario import calculate_scenario
from trading212_analytics.scenario_replay import resolve_scenario_replay
from trading212_application import risk as risk_app
from trading212_application import risk_jobs, scenario_jobs
from trading212_application import scenario as scenario_app
from trading212_domain.risk_serialization import canonical_risk_bytes
from trading212_domain.scenario_serialization import (
    canonical_scenario_bytes,
    encode_scenario_execution,
)
from trading212_persistence import create_database_engine, create_session_factory
from trading212_persistence.base import Base
from trading212_persistence.premium_models import (
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOutboxModel,
    PremiumRunModel,
)
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.risk_job_store import PostgresRiskJobStore
from trading212_persistence.risk_models import (
    RiskComponentModel,
    RiskIntervalModel,
    RiskMatrixCellModel,
    RiskMetricModel,
    RiskResultModel,
    RiskSeriesModel,
)
from trading212_persistence.risk_service import PostgresRiskService
from trading212_persistence.scenario_job_store import PostgresScenarioJobStore
from trading212_persistence.scenario_models import (
    ScenarioAppliedSensitivityModel,
    ScenarioComponentModel,
    ScenarioResultModel,
)
from trading212_persistence.scenario_service import PostgresScenarioService
from trading212_security.principals import Scope
from trading212_worker.historical_seed import CURSOR_KEY, seed_historical_scenarios
from trading212_worker.risk_tasks import (
    CeleryRiskPublisher,
    RiskExecutionState,
    dispatch_risks_once,
    execute_risk_message,
)
from trading212_worker.scenario_tasks import (
    CeleryScenarioPublisher,
    ScenarioExecutionState,
    dispatch_scenarios_once,
    execute_scenario_message,
)
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.phase3_operational_fixture import (
    drop_restored,
    evidence,
    inventory,
    restore_empty,
    task_postgres,
)
from tests.integration.test_historical_seed import NOW
from tests.integration.test_phase3_process_recovery import _celery, _docker, _mapped_port
from tests.integration.test_risk_runs_postgres import RunCase
from tests.integration.test_risk_runs_postgres import run_case as run_case
from tests.integration.test_scenario_runs_postgres import ScenarioCase
from tests.integration.test_scenario_runs_postgres import scenario_case as scenario_case
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration

_ECONOMIC_TABLES = (
    "calculation_runs",
    "cash_balance_observations",
    "cash_flows",
    "dividends",
    "ledger_entries",
    "order_observations",
    "portfolio_snapshots",
    "position_observations",
    "reconciliation_discrepancies",
    "reconciliation_runs",
    "snapshot_cash",
    "snapshot_positions",
    "transactions",
)


@pytest.fixture
async def seeded_history(
    xray_read_case: XrayReadCase,
) -> tuple[sessionmaker[Session], dict[str, str]]:
    """Use the original historical seeder in this one disposable X-ray database."""
    sessions = xray_read_case.sessions
    ids = await seed_historical_scenarios(sessions, app_environment="test")
    return sessions, ids


def _owned_dependencies(engine: Engine) -> dict[str, str]:
    project = os.environ["T212PI_PHASE3_TASK_PROJECT"]
    assert project == "t212pi_batch2_checkpoint_b_20261115"
    assert engine.url.host == "127.0.0.1" and engine.url.port == 55432
    assert engine.url.database and engine.url.database.startswith("t212pi_xray_reads_")
    redis_url = urlparse(os.environ["REDIS_URL"])
    assert redis_url.scheme == "redis" and redis_url.hostname == "127.0.0.1"
    assert redis_url.port == 56379 and redis_url.path == "/0"
    identifiers = {"postgres": task_postgres()}
    for service in ("postgres", "redis"):
        found = _docker(
            "ps",
            "-q",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            f"label=com.docker.compose.service={service}",
        ).split()
        assert len(found) == 1
        identifier = found[0]
        labels = json.loads(_docker("inspect", "--format", "{{json .Config.Labels}}", identifier))
        assert labels["com.docker.compose.project"] == project
        assert labels["com.docker.compose.service"] == service
        identifiers[service] = identifier
        _mapped_port(
            identifier,
            "5432/tcp" if service == "postgres" else "6379/tcp",
            55432 if service == "postgres" else 56379,
        )
    return identifiers


def _dependency_identity(identifiers: dict[str, str]) -> dict[str, Any]:
    result = {}
    for service, identifier in identifiers.items():
        # Deliberately never inspect .Config.Env or process command lines.
        result[service] = {
            "id": _docker("inspect", "--format", "{{.Id}}", identifier),
            "image": _docker("inspect", "--format", "{{.Image}}", identifier),
            "mounts": json.loads(_docker("inspect", "--format", "{{json .Mounts}}", identifier)),
            "networks": {
                name: value["NetworkID"]
                for name, value in json.loads(
                    _docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", identifier)
                ).items()
            },
        }
    return result


async def _ready(engine: Engine, redis: Redis) -> None:
    started = time.monotonic()
    while True:
        try:
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT 1")) == 1
            assert redis.ping()
            return
        except (SQLAlchemyError, RedisError):
            assert time.monotonic() - started < 60
            await asyncio.sleep(0.25)


async def _risk_input(
    service: PostgresRiskService, case: RunCase, run_id: UUID
) -> risk_jobs.RiskExecutionInput:
    def read(session: Session, auth: ReportAuthorization) -> risk_jobs.RiskExecutionInput:
        root, run, _ = service._run_rows(session, auth, run_id)
        return service._current_inputs(session, auth, root, run)

    return await service._execute(case.principal, case.command.account_id, read)


async def _scenario_input(
    service: PostgresScenarioService, case: ScenarioCase
) -> scenario_jobs.ScenarioExecutionInput:
    def read(session: Session, auth: ReportAuthorization) -> scenario_jobs.ScenarioExecutionInput:
        root, run, _ = service._run_rows(session, auth, case.run.id)
        return service._current_inputs(session, auth, root, run)

    return await service._execute(case.principal, case.command.account_id, read)


def _family_counts(sessions: sessionmaker[Session]) -> dict[str, int]:
    with sessions() as session:
        return {
            name: session.scalar(select(func.count()).select_from(table)) or 0
            for name, table in sorted(Base.metadata.tables.items())
            if name.startswith(("risk_", "scenario_"))
        }


def _pending_identity(
    sessions: sessionmaker[Session], identifiers: tuple[UUID, ...]
) -> tuple[Any, ...]:
    with sessions() as session:
        return tuple(
            session.execute(
                select(
                    PremiumRunModel.id,
                    PremiumRunModel.owner_id,
                    PremiumRunModel.account_id,
                    PremiumRunModel.actor_principal_id,
                    PremiumRunModel.input_digest,
                    PremiumRunModel.created_at,
                    PremiumRunModel.expires_at,
                    PremiumJobModel.id,
                    PremiumJobModel.state.label("job_state"),
                    PremiumOutboxModel.id,
                    PremiumOutboxModel.task_name,
                    PremiumOutboxModel.state.label("outbox_state"),
                )
                .join(PremiumJobModel, PremiumJobModel.run_id == PremiumRunModel.id)
                .join(PremiumOutboxModel, PremiumOutboxModel.job_id == PremiumJobModel.id)
                .where(PremiumRunModel.id.in_(identifiers))
                .order_by(PremiumRunModel.id)
            )
        )


def _received(application: Any, queue: str, family: Literal["risk", "scenario"]) -> Any:
    with application.connection_for_read() as connection, connection.SimpleQueue(queue) as incoming:
        delivery = incoming.get(block=True, timeout=10)
        try:
            expected = (
                risk_jobs.RISK_TASK_NAME if family == "risk" else scenario_jobs.SCENARIO_TASK_NAME
            )
            assert delivery.headers["task"] == expected
            payload = delivery.payload
            assert isinstance(payload, (list, tuple)) and len(payload) == 3
            assert payload[0] == [] and isinstance(payload[1], dict)
            message = (
                risk_jobs.RiskTaskMessage.from_wire(payload[1])
                if family == "risk"
                else scenario_jobs.ScenarioTaskMessage.from_wire(payload[1])
            )
            assert delivery.headers["id"] == message.job_id
            delivery.ack()
            return message
        except BaseException:
            delivery.reject(requeue=False)
            raise


async def test_remaining_families_recover_original_queued_work_after_outage_and_clean_restore(
    run_case: RunCase,
    scenario_case: ScenarioCase,
) -> None:
    """Extend the existing projection observation with risk and scenario only."""
    risk, scenario = run_case, scenario_case
    engine = scenario.engine
    assert risk.sessions.kw["bind"] is engine and risk.sessions is scenario.sessions
    identifiers = _owned_dependencies(engine)
    original_dependencies = _dependency_identity(identifiers)
    broker = os.environ["REDIS_URL"]
    redis = Redis.from_url(broker, socket_timeout=2, socket_connect_timeout=2)
    assert cast(dict[str, str], redis.config_get("appendonly"))["appendonly"] == "no"
    assert cast(dict[str, str], redis.config_get("save"))["save"] == ""
    risk_run = await risk.service.create_run(risk.principal, risk.command)
    run_ids = (risk_run.id, scenario.run.id)
    original_risk = await _risk_input(risk.service, risk, risk_run.id)
    original_scenario = await _scenario_input(scenario.service, scenario)
    risk_input_bytes = risk_jobs.risk_execution_bytes(original_risk)
    scenario_input_parts = encode_scenario_execution(original_scenario)
    # Compute the pre-outage baseline outside measured recovery. Neither baseline
    # calculation publishes a result or changes the original queued jobs.
    expected_risk = canonical_risk_bytes(
        calculate_risk(
            original_risk.historical,
            original_risk.definition,
            assets=original_risk.assets,
            xray=original_risk.xray,
        )
    )
    expected_scenario = canonical_scenario_bytes(calculate_scenario(original_scenario))
    original_identity = _pending_identity(risk.sessions, run_ids)
    assert len(original_identity) == 2
    assert all(
        row.job_state == "queued"
        and row.outbox_state == "pending"
        and row.task_name in {risk_jobs.RISK_TASK_NAME, scenario_jobs.SCENARIO_TASK_NAME}
        for row in original_identity
    )
    before = inventory(risk.sessions)
    evidence(
        "remaining-family-pending-boundary",
        {
            "source_inventory": before,
            "families": ["risk", "scenario"],
            "pending_identity_sha256": hashlib.sha256(
                json.dumps(
                    [[str(value) for value in row] for row in original_identity],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "expected_result_sha256": {
                "risk": hashlib.sha256(expected_risk).hexdigest(),
                "scenario": hashlib.sha256(expected_scenario).hexdigest(),
            },
            "dependency_identity": original_dependencies,
            "semantic_clock_scope": (
                "Original fixed source/license fixture instants; no clock advanced."
            ),
        },
    )
    recovered_engine: Engine | None = None
    restored_name: str | None = None
    stopped = False
    primary: BaseException | None = None
    applications: list[Any] = []
    stage = "outage"
    observation: dict[str, Any] = {"families": ["risk", "scenario"], "outcome": "started"}
    started = time.perf_counter()
    try:
        stopped = True
        _docker("kill", "--signal", "KILL", identifiers["postgres"], identifiers["redis"])
        engine.dispose()
        with pytest.raises(SQLAlchemyError), engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        with pytest.raises(RedisError):
            redis.ping()
        _docker("start", identifiers["postgres"], identifiers["redis"])
        await _ready(engine, redis)
        stopped = False
        assert _dependency_identity(identifiers) == original_dependencies
        assert inventory(risk.sessions) == before
        assert _pending_identity(risk.sessions, run_ids) == original_identity
        observation["outage_through_ready_seconds"] = time.perf_counter() - started
        stage = "clean-restore"
        directory = Path(os.environ["T212PI_PHASE3_EVIDENCE_DIR"]) / "operations-backups"
        directory.mkdir(mode=0o700, exist_ok=True)
        restored_name, restored = restore_empty(engine, directory=directory)
        recovered_engine = create_database_engine(engine.url.set(database=restored_name))
        sessions = create_session_factory(recovered_engine)
        restored_inventory = inventory(sessions)
        assert {k: v for k, v in restored_inventory.items() if k != "raw_schema_sha256"} == {
            k: v for k, v in before.items() if k != "raw_schema_sha256"
        }
        assert _pending_identity(sessions, run_ids) == original_identity
        observation.update(restore=restored, restored_inventory=restored_inventory)
        assert restored["backup_and_restore_seconds"] <= 600
        stage = "recovered-worker-execution"
        risk_store = PostgresRiskJobStore(
            sessions,
            cursor_signing_key=CURSOR_KEY,
            preflight=validate_risk_capacity,
            clock=lambda: NOW,
        )
        scenario_store = PostgresScenarioJobStore(
            sessions,
            cursor_signing_key=XRAY_CURSOR_KEY,
            replay_resolver=resolve_scenario_replay,
            clock=lambda: scenario.now,
        )
        assert (
            risk_jobs.risk_execution_bytes(await _risk_input(risk_store, risk, risk_run.id))
            == risk_input_bytes
        )
        assert (
            encode_scenario_execution(await _scenario_input(scenario_store, scenario))
            == scenario_input_parts
        )
        replayed_risk = await risk_store.create_run(
            risk.principal, replace(risk.command, correlation_id="after-restore-risk-retry")
        )
        replayed_scenario = await scenario_store.create_run(
            scenario.principal,
            replace(scenario.command, correlation_id="after-restore-scenario-retry"),
        )
        assert (replayed_risk.id, replayed_risk.job_id, replayed_risk.input_digest) == (
            risk_run.id,
            risk_run.job_id,
            risk_run.input_digest,
        )
        assert (replayed_scenario.id, replayed_scenario.job_id, replayed_scenario.input_digest) == (
            scenario.run.id,
            scenario.run.job_id,
            scenario.run.input_digest,
        )
        assert inventory(sessions) == restored_inventory
        queues = {
            family: "phase3-remaining-" + family + "-" + uuid4().hex
            for family in ("risk", "scenario")
        }
        risk_celery = _celery(broker, queues["risk"])
        scenario_celery = _celery(broker, queues["scenario"])
        applications.extend((risk_celery, scenario_celery))
        risk_publisher = CeleryRiskPublisher(risk_celery)
        scenario_publisher = CeleryScenarioPublisher(scenario_celery)
        risk_dispatch = await dispatch_risks_once(
            risk_store, risk_publisher, dispatcher_id="restored-risk-dispatcher"
        )
        assert (risk_dispatch.claimed, risk_dispatch.published, risk_dispatch.deferred) == (1, 1, 0)
        assert redis.llen(queues["risk"]) == 1
        risk_message = _received(risk_celery, queues["risk"], "risk")
        assert risk_message.run_id == str(risk_run.id)
        assert (
            await execute_risk_message(
                risk_store, risk_message, consumer_id="restored-risk-worker", clock=lambda: NOW
            )
            is RiskExecutionState.SUCCEEDED
        )
        scenario_dispatch = await dispatch_scenarios_once(
            scenario_store, scenario_publisher, dispatcher_id="restored-scenario-dispatcher"
        )
        assert (
            scenario_dispatch.claimed,
            scenario_dispatch.published,
            scenario_dispatch.deferred,
        ) == (1, 1, 0)
        assert redis.llen(queues["scenario"]) == 1
        scenario_message = _received(scenario_celery, queues["scenario"], "scenario")
        assert scenario_message.run_id == str(scenario.run.id)
        assert (
            await execute_scenario_message(
                scenario_store,
                scenario_message,
                consumer_id="restored-scenario-worker",
                clock=lambda: scenario.now,
            )
            is ScenarioExecutionState.SUCCEEDED
        )
        risk_view = await risk_store.get_run(risk.principal, risk_run.id)
        scenario_view = await scenario_store.get_run(
            scenario.principal, scenario.run.id, scenario_app.ScenarioComponentPageQuery()
        )
        assert (
            risk_view.state is risk_app.PremiumJobState.SUCCEEDED and risk_view.result is not None
        )
        assert (
            scenario_view.state is risk_app.PremiumJobState.SUCCEEDED
            and scenario_view.result is not None
        )
        with sessions() as session:
            risk_result = session.scalars(
                select(RiskResultModel).where(RiskResultModel.run_id == risk_run.id)
            ).one()
            scenario_result = session.scalars(
                select(ScenarioResultModel).where(ScenarioResultModel.run_id == scenario.run.id)
            ).one()
            assert risk_result.canonical_result == expected_risk
            assert scenario_result.canonical_result == expected_scenario
            for model, expected_count in (
                (RiskSeriesModel, risk_result.series_count),
                (RiskIntervalModel, risk_result.interval_count),
                (RiskMatrixCellModel, risk_result.matrix_cell_count),
                (RiskMetricModel, risk_result.metric_count),
                (RiskComponentModel, risk_result.component_count),
                (ScenarioComponentModel, scenario_result.component_count),
                (ScenarioAppliedSensitivityModel, scenario_result.applied_use_count),
            ):
                result_id = (
                    risk_result.id
                    if model.__tablename__.startswith("risk_")
                    else scenario_result.id
                )
                count = session.scalar(
                    select(func.count()).select_from(model).where(model.result_id == result_id)
                )
                assert count == expected_count
            retained_results = {}
            for family, payload in (
                ("risk", risk_result.canonical_result),
                ("scenario", scenario_result.canonical_result),
            ):
                path = directory / ("recovered-" + family + "-" + uuid4().hex + ".bin")
                descriptor = os.open(
                    path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
                )
                with os.fdopen(descriptor, "wb") as output:
                    output.write(payload)
                retained_results[family] = {
                    "file": path.name,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            observation["actual_recovered_canonical_results"] = retained_results
            capacity = session.get_one(PremiumCapacityModel, UUID(risk.principal.owner_id))
            assert capacity.active_jobs == capacity.reserved_bytes == 0
            assert capacity.retained_bytes > 0
        counts = _family_counts(sessions)
        assert counts["risk_results"] == counts["scenario_results"] == 1
        final = inventory(sessions)
        assert {n: final["tables"][n] for n in _ECONOMIC_TABLES} == {
            n: before["tables"][n] for n in _ECONOMIC_TABLES
        }
        await risk_publisher.publish_risk(risk_message)
        duplicate_risk = _received(risk_celery, queues["risk"], "risk")
        assert duplicate_risk == risk_message
        assert (
            await execute_risk_message(
                risk_store, duplicate_risk, consumer_id="restored-risk-duplicate", clock=lambda: NOW
            )
            is RiskExecutionState.FENCED
        )
        await scenario_publisher.publish_scenario(scenario_message)
        duplicate_scenario = _received(scenario_celery, queues["scenario"], "scenario")
        assert duplicate_scenario == scenario_message
        assert (
            await execute_scenario_message(
                scenario_store,
                duplicate_scenario,
                consumer_id="restored-scenario-duplicate",
                clock=lambda: scenario.now,
            )
            is ScenarioExecutionState.FENCED
        )
        assert _family_counts(sessions) == counts and inventory(sessions) == final
        assert all(redis.llen(queue) == 0 for queue in queues.values())
        stage = "post-restore-authorization"
        private_selects = 0

        def reject_private_select(
            _connection: Any,
            _cursor: Any,
            statement: str,
            _parameters: Any,
            _context: Any,
            _many: bool,
        ) -> None:
            nonlocal private_selects
            lowered = statement.lower()
            if lowered.lstrip().startswith("select") and any(
                token in lowered
                for token in ("canonical_input", "canonical_result", "canonical_component")
            ):
                private_selects += 1
                raise AssertionError("An unauthorized read reached private payload selection.")

        denied_risk = replace(risk.principal, scopes=risk.principal.scopes - {Scope.ANALYTICS_READ})
        denied_scenario = replace(
            scenario.principal, scopes=scenario.principal.scopes - {Scope.ANALYTICS_READ}
        )
        event.listen(recovered_engine, "before_cursor_execute", reject_private_select)
        try:
            with pytest.raises(risk_app.RiskServiceError) as risk_denied:
                await risk_store.get_run(denied_risk, risk_run.id)
            assert risk_denied.value.code is risk_app.RiskErrorCode.ACCESS_DENIED
            with pytest.raises(scenario_app.ScenarioServiceError) as scenario_denied:
                await scenario_store.get_run(
                    denied_scenario, scenario.run.id, scenario_app.ScenarioComponentPageQuery()
                )
            assert scenario_denied.value.code is scenario_app.ScenarioErrorCode.ACCESS_DENIED
        finally:
            event.remove(recovered_engine, "before_cursor_execute", reject_private_select)
        assert private_selects == 0
        assert inventory(sessions) == final
        assert inventory(risk.sessions) == before
        elapsed = time.perf_counter() - started
        assert elapsed <= 600
        observation.update(
            outcome="passed",
            total_recovery_seconds=elapsed,
            recovery_limit_seconds=600,
            same_dependency_identities=True,
            original_pending_identities_preserved=True,
            exact_input_parts_preserved=True,
            canonical_results_equal_to_pre_outage_baseline=True,
            semantic_command_retry_preserves_identity_and_capacity=True,
            normalized_family_counts=counts,
            original_economic_tables_unchanged=13,
            duplicate_broker_delivery_fenced=True,
            unauthorized_private_payload_selects=private_selects,
            source_database_unchanged=True,
            scope=(
                "Risk/scenario queued work; actual PG/Redis outage and empty restore; "
                "no all-nine or production claim."
            ),
        )
    except BaseException as error:
        primary = error
        observation.update(outcome="failed", error_type=type(error).__name__)
        raise
    finally:
        observation["last_stage"] = stage
        observation["elapsed_seconds"] = time.perf_counter() - started
        cleanup_failure: Exception | None = None
        if stopped:
            try:
                _docker("start", identifiers["postgres"], identifiers["redis"])
                await _ready(engine, redis)
            except Exception as cleanup:
                cleanup_failure = cleanup
                observation["dependency_cleanup_error_type"] = type(cleanup).__name__
                if primary is not None:
                    primary.add_note(
                        "Exact task dependency recovery failed; inspect private metadata."
                    )
        if recovered_engine is not None:
            recovered_engine.dispose()
        if restored_name is not None:
            observation["restored_target"] = restored_name
            try:
                drop_restored(engine, restored_name)
                observation["restored_target_removed"] = True
            except Exception as cleanup:
                cleanup_failure = cleanup_failure or cleanup
                observation["restore_cleanup_error_type"] = type(cleanup).__name__
                if primary is not None:
                    primary.add_note("Exact restored target remains after cleanup failure.")
        for application in applications:
            application.close()
        redis.close()
        if cleanup_failure is not None and primary is None:
            observation.update(outcome="failed", error_type=type(cleanup_failure).__name__)
        try:
            evidence("remaining-family-recovery-terminal", observation)
        except Exception as recording:
            if primary is not None:
                primary.add_note("Recovery terminal recording failed: " + type(recording).__name__)
            elif cleanup_failure is not None:
                cleanup_failure.add_note(
                    "Terminal recording also failed: " + type(recording).__name__
                )
            else:
                raise
        if cleanup_failure is not None and primary is None:
            raise cleanup_failure
