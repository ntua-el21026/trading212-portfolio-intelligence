"""Actual private child execution, exact output and bounded cancellation without Docker."""

import os
import subprocess
import threading
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from trading212_analytics.risk import calculate_risk
from trading212_application import risk_jobs as jobs
from trading212_domain.risk_serialization import canonical_risk_bytes
from trading212_worker.risk_process import calculate_private_risk

from tests.unit.analytics.historical_factories import fixture
from tests.unit.analytics.test_risk_history import definition

pytestmark = pytest.mark.unit


def inputs() -> jobs.RiskExecutionInput:
    value = fixture(("100", "110") * 21)
    return jobs.RiskExecutionInput(
        historical=value,
        definition=definition(value),
        assets=(),
        xray=None,
        input_digest="e" * 64,
        expires_at=value.selection.window.source_cutoff_at + timedelta(days=1),
    )


def test_actual_child_matches_in_process_canonical_bytes_and_exits() -> None:
    value = inputs()
    with patch(
        "trading212_worker.risk_process.subprocess.Popen", wraps=subprocess.Popen
    ) as launched:
        actual = calculate_private_risk(value, cancelled=threading.Event())
    assert launched.call_count == 1
    expected = calculate_risk(value.historical, value.definition)
    assert canonical_risk_bytes(actual) == canonical_risk_bytes(expected)
    assert launched.call_args.kwargs["env"] == {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}
    assert launched.call_args.kwargs["stdout"] is subprocess.DEVNULL


def test_cancelled_before_start_creates_no_process() -> None:
    cancelled = threading.Event()
    cancelled.set()
    with (
        patch("trading212_worker.risk_process.subprocess.Popen") as launched,
        pytest.raises(jobs.RiskJobInputError) as failure,
    ):
        calculate_private_risk(inputs(), cancelled=cancelled)
    assert failure.value.code is jobs.RiskJobFailureCode.LEASE_EXPIRED
    launched.assert_not_called()


def test_actual_deadline_kills_and_reaps_child() -> None:
    processes: list[subprocess.Popen[bytes]] = []
    original = subprocess.Popen

    def launch(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    with (
        patch("trading212_worker.risk_process.subprocess.Popen", side_effect=launch),
        pytest.raises(jobs.RiskJobInputError) as failure,
    ):
        calculate_private_risk(inputs(), cancelled=threading.Event(), maximum_seconds=0.000001)
    assert failure.value.code is jobs.RiskJobFailureCode.LIMIT_EXCEEDED
    assert len(processes) == 1 and processes[0].poll() is not None
    assert not any(thread.name == "risk-child-deadline" for thread in threading.enumerate())


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
        jobs.RiskTaskMessage.from_wire(wire)


def test_message_has_no_transport_or_financial_extension_points() -> None:
    identifier = "00000000-0000-0000-0000-000000000000"
    wire = jobs.RiskTaskMessage(identifier, identifier, identifier, identifier, "a" * 64).to_wire()
    for field in ("url", "returns", "sql", "quantity", "broker_order"):
        with pytest.raises(ValueError):
            jobs.RiskTaskMessage.from_wire({**wire, field: "forbidden"})
