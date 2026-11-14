"""Measured local workloads, with frozen operational bounds and disclosed scope."""

from __future__ import annotations

import math
import os
import platform
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import event
from trading212_application import projection as app
from trading212_application import research as research_app
from trading212_application.projection_views import ProjectionVersionMetadata
from trading212_domain import reports
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
)
from trading212_domain.research_facts import copy_research_portfolio_facts
from trading212_domain.research_serialization import research_record_digest
from trading212_persistence.projection_job_store import PostgresProjectionJobStore
from trading212_persistence.report_job_store import PostgresReportJobStore
from trading212_persistence.report_service import PostgresReportService
from trading212_worker.report_tasks import ReportExecutionState, execute_report_message
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.phase3_operational_fixture import evidence
from tests.integration.phase3_projection_budget_worker import measure_projection_attempt
from tests.integration.projection_job_fixture import ProjectionJobCase
from tests.integration.projection_job_fixture import projection_job_case as projection_job_case
from tests.integration.research_case import research_case as research_case
from tests.integration.research_report_case import ResearchReportCase, generate, message, selection
from tests.integration.research_report_case import research_report_case as research_report_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


def _summary(samples: list[float]) -> dict[str, float | int]:
    ordered = sorted(samples)
    return {
        "samples": len(ordered),
        "p50_seconds": ordered[math.ceil(len(ordered) * 0.50) - 1],
        "p95_seconds": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "max_seconds": ordered[-1],
    }


def _host() -> dict[str, object]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
    }


async def test_measured_research_read_query_and_report_admission_budgets(
    research_report_case: ResearchReportCase,
) -> None:
    case = research_report_case
    query = replace(case.research.query(), source_cutoff_at=case.item.source_cutoff_at)
    # Establish independent canonical financial proof before warmup or timed SQL counting.
    with case.research.xray.sessions() as session, session.begin():
        pin, value, _, _ = case.research.service.retained_xray(
            session, case.research.auth(session), case.research.run_id
        )
        expected_facts = copy_research_portfolio_facts(pin, value, case.research.entity_id)
    facts_digest = research_record_digest(expected_facts)
    assert case.item.portfolio.pin == pin
    assert case.item.portfolio.canonical_facts_digest == facts_digest
    assert case.item.source.content_digest == case.event.content_digest

    def assert_exact_page(result: research_app.ResearchSummary) -> None:
        # This check runs after each sample ends; no semantic work enters its timed interval.
        assert result.total == 1 and len(result.items) == 1 and result.next_cursor is None
        assert result.pin == pin and result.source_cutoff_at == query.source_cutoff_at
        item = result.items[0]
        assert item.item_id == case.item.item_id
        assert item.source_cutoff_at == case.item.source_cutoff_at
        assert item.source.content_digest == case.event.content_digest
        assert tuple(citation.source.content_digest for citation in item.source.citations) == tuple(
            citation.source.content_digest for citation in case.event.citations
        )
        assert item.portfolio.pin == pin
        assert item.portfolio.canonical_facts_digest == facts_digest
        assert item.portfolio.effective_exposure == expected_facts.effective_exposure

    counts: list[int] = []
    durations: list[float] = []
    admissions: list[float] = []
    completions: list[dict[str, object]] = []
    statements = [0]
    phase = "warmup"
    failure_type = None
    # Operational latency uses wall time. The untimed production worker must
    # likewise acquire/renew its lease at real UTC, matching the SQL guards.
    worker = PostgresReportJobStore(case.research.xray.sessions, clock=lambda: datetime.now(UTC))
    status_reader = PostgresReportService(
        case.research.xray.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: datetime.now(UTC),
        contract_version=3,
    )

    def count_sql(*_args: Any) -> None:
        statements[0] += 1

    try:
        assert_exact_page(
            await case.research.service.get_research_summary(case.research.xray.principal, query)
        )
        phase = "research_reads"
        event.listen(case.research.xray.engine, "before_cursor_execute", count_sql)
        try:
            for _ in range(30):
                statements[0] = 0
                started = perf_counter()
                try:
                    result = await case.research.service.get_research_summary(
                        case.research.xray.principal, query
                    )
                finally:
                    durations.append(perf_counter() - started)
                    counts.append(statements[0])
                assert_exact_page(result)
        finally:
            event.remove(case.research.xray.engine, "before_cursor_execute", count_sql)
        for ordinal in range(10):
            phase = "report_admission"
            started = perf_counter()
            try:
                pending = await generate(
                    case, selected=selection(case, formats=(reports.ReportFormat.JSON,))
                )
            finally:
                admissions.append(perf_counter() - started)
            phase = "untimed_report_completion"
            state = await execute_report_message(
                worker, message(case, pending), consumer_id="measured-service-budgets"
            )
            completed = await status_reader.get_report_status(
                case.research.xray.principal, case.research.account_id, pending.job_id
            )
            completions.append(
                {
                    "admission_ordinal": ordinal + 1,
                    "worker_outcome": state.value,
                    "job_state": completed.state.value,
                    "failure_code": None
                    if completed.failure_code is None
                    else completed.failure_code.value,
                }
            )
            assert state is ReportExecutionState.COMPLETED, completed.failure_code
            assert completed.state is reports.ReportJobState.SUCCEEDED
        phase = "thresholds"
        assert len(counts) == len(durations) == 30
        assert len(admissions) == len(completions) == 10
        assert max(counts) <= 12
        assert _summary(durations)["p95_seconds"] <= 0.500
        assert _summary(admissions)["p95_seconds"] <= 0.750
        phase = "complete"
    except Exception as error:
        failure_type = type(error).__name__
        raise
    finally:
        evidence(
            "service-budgets",
            {
                "host": _host(),
                "scope": (
                    "One-source retained research page and new report admissions; "
                    "production service ports, serial, no HTTP transport timing."
                ),
                "quantile_method": "nearest_rank",
                "measurement_phase": phase,
                "measurement_completed": phase == "complete",
                "failure_type": failure_type,
                "samples_include_failed_call_if_present": True,
                "verified_page": {
                    "total": 1,
                    "item_id": str(case.item.item_id),
                    "event_revision_digest": case.event.content_digest,
                    "source_version_digests": [
                        citation.source.content_digest for citation in case.event.citations
                    ],
                    "xray_pin_digest": research_record_digest(pin),
                    "canonical_facts_digest": facts_digest,
                    "assertion_timing": "outside each measured read interval",
                },
                "read_samples_seconds": durations,
                "admission_samples_seconds": admissions,
                "read": _summary(durations) if durations else None,
                "read_statement_counts": counts,
                "admission": _summary(admissions) if admissions else None,
                "untimed_report_completions": completions,
                "completion_clock": "real UTC production job store and status reader",
                "thresholds": {
                    "read_p95_seconds": 0.500,
                    "admission_p95_seconds": 0.750,
                    "page_sql_statements": 12,
                    "required_read_samples": 30,
                    "required_admission_samples": 10,
                },
            },
        )


async def test_maximum_work_product_projection_attempt_has_measured_time_and_child_rss(
    projection_job_case: ProjectionJobCase,
) -> None:
    case = projection_job_case
    modeled_value = case.command.selection.initial.modeled_value
    assert modeled_value is not None
    await case.service.cancel_run(
        case.principal,
        app.CancelProjectionRun(
            run_id=case.run.id, idempotency_key=uuid4().hex, correlation_id="measure-initial-cancel"
        ),
    )
    assets = tuple(
        ProjectionAsset(
            key=f"modeled-{i}",
            annual_mean_log_return=Decimal(".04"),
            annual_volatility=Decimal(".1"),
            weight=Decimal(".125"),
        )
        for i in range(8)
    )
    assumptions = ProjectionAssumptions(
        assets=assets,
        correlation=tuple(tuple(Decimal(int(i == j)) for j in range(8)) for i in range(8)),
        reporting_currency=modeled_value.currency,
        annual_inflation=Decimal(".02"),
        annual_fee=Decimal(".001"),
        annual_tax_drag=Decimal(".002"),
    )
    definition = await case.service.create_assumption_set(
        case.principal,
        app.CreateAssumptionSet(
            account_id=case.command.selection.account_id,
            metadata=ProjectionVersionMetadata(
                name="Operational maximum work",
                description="Eight independent stochastic modeled assets; no provider input",
            ),
            content=assumptions,
            idempotency_key=uuid4().hex,
            correlation_id="operational-maximum",
        ),
    )
    selected = replace(
        case.command.selection,
        assumption_version_id=definition.current_version_id,
        months=250,
        paths=500,
        retained_months=(0, 250),
        allocation=tuple(ProjectionAllocation(key=a.key, weight=a.weight) for a in assets),
    )
    run = await case.service.create_run(
        case.principal, replace(case.command, selection=selected, idempotency_key=uuid4().hex)
    )
    worker = PostgresProjectionJobStore(
        case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: datetime.now(UTC)
    )
    claims = await worker.claim_projection_dispatches(dispatcher_id="operational-maximum")
    assert len(claims) == 1 and claims[0].message.run_id == str(run.id)
    assert await worker.acknowledge_projection_dispatch(claims[0])
    measured = await measure_projection_attempt(
        case.engine.url.render_as_string(hide_password=False), claims[0].message.to_wire()
    )
    record = {
        "host": _host(),
        "work_product": 8 * 250 * 500,
        "assets": 8,
        "months": 250,
        "paths": 500,
        "retained_months": [0, 250],
        "annual_volatility": "0.1",
        "measurement": measured,
        "thresholds": {"attempt_seconds": 240, "worker_tree_rss_bytes": 512 * 1024 * 1024},
        "memory_scope": (
            "Externally sampled concurrent RSS sum of a fresh dedicated production worker "
            "and its own descendants, including numerical-child execution and startup/imports. "
            "Linux /proc PID start ticks and private session/group validate ownership. "
            "Per-PID reads are sequential, target cadence 50 ms; between-sample transients "
            "are not measured. Child VmHWM is a separate metric, never added to another peak. "
            "Pytest, DB/Redis servers and the external sampler are outside the attempt tree."
        ),
        "time_scope": (
            "One real-UTC production execute_projection_message attempt, including claim, "
            "actual stored input loading, callbacks/checkpoints and publication. Startup, "
            "post-attempt header inspection and cleanup are separately recorded. The test "
            "adds bounded metadata/digest observations; external /proc sampling has host "
            "overhead. This is one 8-asset,250-month,500-path baseline geometry with two "
            "retained months, not every geometry or the maximum retained-byte workload."
        ),
    }
    evidence("maximum-work", record)
    assert measured["failure"] is None, record
    assert measured["cleanup"]["worker_exitcode"] == 0, record
    assert measured["cleanup"]["remaining_live_pids"] == [], record
    assert measured["cleanup"]["remaining_zombie_pids"] == [], record
    terminal = measured["terminal"]
    assert terminal is not None and terminal["kind"] == "terminal", record
    assert terminal["outcome"] == "succeeded", record
    assert len(terminal["loaded_plans"]) == 1, record
    loaded = terminal["loaded_plans"][0]
    assert (
        loaded["work_units"],
        loaded["assets"],
        loaded["months"],
        loaded["paths"],
        loaded["variants"],
        loaded["retained_months"],
    ) == (1_000_000, 8, 250, 500, 1, [0, 250]), record
    assert loaded["captured_input_digest"] == claims[0].message.input_digest
    assert terminal["result_count"] == 1, record
    assert terminal["result_headers"][0]["sealed"] is True
    assert terminal["result_headers"][0]["input_digest"] == loaded["numerical_input_digest"]
    assert len(terminal["result_headers"][0]["result_digest"]) == 64
    assert terminal["attempt_seconds"] <= 240, record
    assert measured["maximum_pid_count"] >= 2, record
    assert all(sample["measurement_available"] for sample in measured["rss_samples"]), record
    assert measured["peak_worker_tree_rss_bytes"] <= 512 * 1024 * 1024, record
    assert loaded["peak_child_rss_bytes"] is not None, record
    assert loaded["peak_child_rss_bytes"] <= 512 * 1024 * 1024, record
