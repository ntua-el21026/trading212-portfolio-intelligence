"""Fail-closed ping-response and privacy checks for the bounded worker probe."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest
from trading212_worker.health_probe import main


class _Inspector:
    def __init__(self, response: object, *, fail: bool = False) -> None:
        self.response = response
        self.fail = fail

    def ping(self) -> object:
        if self.fail:
            raise RuntimeError("Diagnostic content must remain private")
        return self.response


class _Control:
    def __init__(self, inspector: _Inspector) -> None:
        self.inspector = inspector
        self.calls: list[tuple[int, int]] = []

    def inspect(self, *, timeout: int, limit: int) -> _Inspector:
        self.calls.append((timeout, limit))
        return self.inspector


def _application(monkeypatch: pytest.MonkeyPatch, inspector: _Inspector) -> _Control:
    control = _Control(inspector)
    module = ModuleType("trading212_worker.tasks")
    module.__dict__["celery_app"] = SimpleNamespace(control=control)
    monkeypatch.setitem(sys.modules, "trading212_worker.tasks", module)
    return control


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"worker": {"ok": "pong"}}, 0),
        ({}, 1),
        (None, 1),
        ({"worker": {"error": "pong"}}, 1),
        ({"worker": {"ok": "unavailable"}}, 1),
        ({"worker": "pong"}, 1),
        ([{"ok": "pong"}], 1),
    ],
)
def test_probe_requires_a_valid_reply_without_collecting_unneeded_nodes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    response: object,
    expected: int,
) -> None:
    control = _application(monkeypatch, _Inspector(response))
    assert main() == expected
    assert control.calls == [(5, 1)]
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_probe_errors_fail_closed_without_disclosing_diagnostics(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    control = _application(monkeypatch, _Inspector(None, fail=True))
    assert main() == 1
    assert control.calls == [(5, 1)]
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_probe_missing_application_fails_without_logging(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(
        sys.modules, "trading212_worker.tasks", ModuleType("trading212_worker.tasks")
    )
    assert main() == 1
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_probe_unavailable_application_fails_without_logging(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = ModuleType("trading212_worker.tasks")
    module.__dict__["celery_app"] = None
    monkeypatch.setitem(sys.modules, "trading212_worker.tasks", module)
    assert main() == 1
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
