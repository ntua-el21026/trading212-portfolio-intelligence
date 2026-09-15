"""Actual private child execution, exact output and bounded cancellation without Docker."""

import os
import subprocess
import threading
from typing import Any
from unittest.mock import patch

import pytest
from trading212_analytics.scenario import calculate_scenario
from trading212_application import scenario_jobs as jobs
from trading212_domain.scenario_serialization import canonical_scenario_bytes
from trading212_worker.scenario_process import calculate_private_scenario

from tests.unit.analytics.scenario_factories import content, input_for, portfolio, price

pytestmark = pytest.mark.unit


def inputs() -> jobs.ScenarioExecutionInput:
    return input_for(portfolio(("100",)), content(price(10, "-0.2")))


def test_actual_child_matches_in_process_canonical_bytes_and_exits() -> None:
    value = inputs()
    with patch(
        "trading212_worker.scenario_process.subprocess.Popen", wraps=subprocess.Popen
    ) as launched:
        actual = calculate_private_scenario(value, cancelled=threading.Event())
    assert launched.call_count == 1
    expected = calculate_scenario(value)
    assert canonical_scenario_bytes(actual) == canonical_scenario_bytes(expected)
    assert launched.call_args.kwargs["env"] == {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}
    assert launched.call_args.kwargs["stdout"] is subprocess.DEVNULL


def test_cancelled_before_start_creates_no_process() -> None:
    cancelled = threading.Event()
    cancelled.set()
    with (
        patch("trading212_worker.scenario_process.subprocess.Popen") as launched,
        pytest.raises(jobs.ScenarioJobInputError) as failure,
    ):
        calculate_private_scenario(inputs(), cancelled=cancelled)
    assert failure.value.code is jobs.ScenarioJobFailureCode.LEASE_EXPIRED
    launched.assert_not_called()


def test_actual_deadline_kills_and_reaps_child() -> None:
    processes: list[subprocess.Popen[bytes]] = []
    original = subprocess.Popen

    def launch(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    with (
        patch("trading212_worker.scenario_process.subprocess.Popen", side_effect=launch),
        pytest.raises(jobs.ScenarioJobInputError) as failure,
    ):
        calculate_private_scenario(inputs(), cancelled=threading.Event(), maximum_seconds=0.000001)
    assert failure.value.code is jobs.ScenarioJobFailureCode.LIMIT_EXCEEDED
    assert len(processes) == 1 and processes[0].poll() is not None
    assert not any(thread.name == "scenario-child-deadline" for thread in threading.enumerate())


@pytest.mark.parametrize(
    "field,value",
    [
        ("job_id", "../job"),
        ("owner_id", " 00000000-0000-0000-0000-000000000000"),
        ("input_digest", "x" * 64),
        ("account_id", 12),
    ],
)
def test_message_rejects_noncanonical_identity_and_digest(field: str, value: object) -> None:
    wire: dict[str, object] = {
        key: "00000000-0000-0000-0000-000000000000"
        for key in ("job_id", "run_id", "owner_id", "account_id")
    }
    wire["input_digest"] = "a" * 64
    wire[field] = value
    with pytest.raises(ValueError):
        jobs.ScenarioTaskMessage.from_wire(wire)


def test_message_has_no_transport_or_financial_extension_points() -> None:
    identifier = "00000000-0000-0000-0000-000000000000"
    wire = jobs.ScenarioTaskMessage(
        identifier, identifier, identifier, identifier, "a" * 64
    ).to_wire()
    for field in ("url", "returns", "sql", "quantity", "broker_order"):
        with pytest.raises(ValueError):
            jobs.ScenarioTaskMessage.from_wire({**wire, field: "forbidden"})
