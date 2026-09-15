"""Application admission accepts saved pins, never caller-supplied coefficient arrays."""

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from trading212_application.scenario import (
    CancelScenarioRun,
    CreateScenario,
    CreateScenarioRun,
    CreateScenarioVersion,
    ScenarioComponentPageQuery,
)
from trading212_domain.errors import DomainError

from tests.unit.analytics.xray_factories import EUR, uid
from tests.unit.domain.scenario_factories import definition


def create_run() -> CreateScenarioRun:
    return CreateScenarioRun(
        account_id=uid(2),
        scenario_version_id=uid(900),
        portfolio_snapshot_id=uid(3),
        xray_run_id=uid(8003),
        reporting_currency=EUR,
        source_cutoff_at=datetime(2026, 9, 8, 12, tzinfo=timezone(timedelta(hours=3))),
        idempotency_key="scenario-run-admission",
        correlation_id="scenario-command-fixture",
    )


def test_create_run_has_only_explicit_saved_pins_and_canonical_currency_time() -> None:
    command = create_run()
    assert command.source_cutoff_at == datetime(2026, 9, 8, 9, tzinfo=UTC)
    assert command.source_cutoff_at.utcoffset() == timedelta(0)
    assert command.replay is None
    assert {field.name for field in fields(command)} == {
        "idempotency_key",
        "correlation_id",
        "account_id",
        "scenario_version_id",
        "portfolio_snapshot_id",
        "xray_run_id",
        "reporting_currency",
        "source_cutoff_at",
        "replay",
    }


def test_definition_and_version_commands_keep_exact_owner_content() -> None:
    content = definition()
    created = CreateScenario(
        account_id=uid(2),
        content=content,
        idempotency_key="scenario-create-fixture",
        correlation_id="scenario-command-fixture",
    )
    versioned = CreateScenarioVersion(
        scenario_id=uid(900),
        expected_revision=1,
        content=content,
        idempotency_key="scenario-version-fixture",
        correlation_id="scenario-command-fixture",
    )
    assert created.content is versioned.content is content
    with pytest.raises(DomainError):
        replace(versioned, expected_revision=True)
    with pytest.raises(DomainError):
        replace(versioned, expected_revision=513)


def test_commands_reject_empty_request_identity_and_naive_cutoff() -> None:
    with pytest.raises(DomainError):
        replace(create_run(), source_cutoff_at=datetime(2026, 9, 8))
    with pytest.raises(DomainError):
        replace(create_run(), idempotency_key="")
    with pytest.raises(DomainError):
        CancelScenarioRun(run_id=uid(2), idempotency_key="valid-key-fixture", correlation_id="")


@pytest.mark.parametrize("cursor", ["", "a" * 2049])
def test_component_cursor_text_is_bounded_before_service_use(cursor: str) -> None:
    with pytest.raises(DomainError):
        ScenarioComponentPageQuery(component_cursor=cursor)
