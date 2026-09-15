"""Closed third-profile metadata and authorization without loading report bytes."""

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from sqlalchemy import CheckConstraint, Table
from sqlalchemy.orm import Session
from trading212_persistence import report_premium_sources as sources
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.report_models import (
    ReportInputPremiumDependencyModel,
    ReportInputSnapshotModel,
    ReportJobModel,
)
from trading212_security.principals import AuthorizationError

from tests.unit.analytics.xray_factories import AT, uid

pytestmark = pytest.mark.unit


def constants(name: str) -> dict[str, object]:
    tree = ast.parse(Path("migrations/versions", name).read_text())
    return {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def test_0021_restores_exact_frozen_0019_guards_and_rejects_destructive_downgrade() -> None:
    old = constants("20260915_0019_premium_reports.py")
    current = constants("20260915_0021_premium_report_profiles.py")
    assert current["down_revision"] == "20260915_0020"
    assert current["_PREVIOUS_GUARDS"] == old["_GUARDS"]
    assert current["_SCENARIO_COPY_TABLES"] == (
        "scenario_run_payloads",
        "scenario_results",
        "scenario_components",
        "scenario_applied_sensitivities",
    )
    source = Path("migrations/versions/20260915_0021_premium_report_profiles.py").read_text()
    assert source.index("Third-profile reports must be absent before downgrade") < source.index(
        "DROP TRIGGER reports_premium_copy_guard"
    )
    tree = ast.parse(source)
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("trading212_")
        for node in ast.walk(tree)
    )


def test_profile3_is_report_only_and_normalized_pins_are_complete_or_legacy_null() -> None:
    def checks(table: Table) -> str:
        return " ".join(str(x.sqltext) for x in table.constraints if isinstance(x, CheckConstraint))

    assert "contract_version IN (1,2,3,4) AND (kind='report' OR contract_version=1)" in checks(
        cast(Table, ReportInputSnapshotModel.__table__)
    )
    assert "contract_version IN (1,2,3,4)" in checks(cast(Table, ReportJobModel.__table__))
    dependency = cast(Table, ReportInputPremiumDependencyModel.__table__)
    assert "kind IN ('risk','scenario','projection')" in checks(dependency)
    assert "IN (0,8)" in checks(dependency)
    assert {
        "result_id",
        "definition_version_id",
        "definition_digest",
        "snapshot_id",
        "snapshot_digest",
        "reporting_currency",
        "source_cutoff_at",
        "valuation_at",
    } <= set(dependency.c.keys())
    assert not {"risk_run_id", "scenario_run_id"} & set(dependency.c.keys())


@pytest.mark.parametrize(("version", "kind"), [(3, "scenario"), (3, "risk"), (2, "risk")])
def test_authorization_dispatch_uses_actual_family_and_only_permanent_metadata(
    version: int, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = Mock(spec=Session)
    session.scalar.side_effect = [version, False, None]
    dependency = SimpleNamespace(
        kind=kind, run_id=uid(10), input_digest="a" * 64, result_digest="b" * 64
    )
    session.scalars.return_value.all.return_value = [dependency]
    auth = Mock(spec=ReportAuthorization)
    auth.owner_id, auth.account_id = uid(1), uid(2)
    actual = Mock(
        return_value=(
            SimpleNamespace(input_digest="a" * 64),
            Mock(),
            Mock(),
            SimpleNamespace(content_digest="b" * 64),
        )
    )
    other = Mock(side_effect=AssertionError("wrong premium family"))
    monkeypatch.setattr(sources, "_scenario_metadata", actual if kind == "scenario" else other)
    monkeypatch.setattr(
        sources, "authorize_risk_report_metadata", actual if kind == "risk" else other
    )
    sources.authorize_report_premium_sources(
        session, cast(ReportAuthorization, auth), input_id=uid(3), now=AT.value
    )
    actual.assert_called_once()
    other.assert_not_called()
    for call in session.scalar.call_args_list:
        assert "canonical_" not in str(call.args[0])


@pytest.mark.parametrize(
    ("version", "kind", "count"),
    [
        (1, "scenario", 1),
        (2, "scenario", 1),
        (3, "scenario", 0),
        (3, "scenario", 2),
        (3, "projection", 1),
    ],
)
def test_profile_and_single_dependency_mismatches_fail_closed(
    version: int, kind: str, count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = Mock(spec=Session)
    session.scalar.side_effect = [version, False]
    session.scalars.return_value.all.return_value = [
        SimpleNamespace(kind=kind, run_id=uid(10)) for _ in range(count)
    ]
    auth = Mock(spec=ReportAuthorization)
    auth.owner_id, auth.account_id = uid(1), uid(2)
    private = Mock(side_effect=AssertionError("metadata dispatch must reject"))
    monkeypatch.setattr(sources, "_scenario_metadata", private)
    monkeypatch.setattr(sources, "authorize_risk_report_metadata", private)
    with pytest.raises(AuthorizationError):
        sources.authorize_report_premium_sources(
            session, cast(ReportAuthorization, auth), input_id=uid(3), now=AT.value
        )
    private.assert_not_called()


@pytest.mark.parametrize("restricted", [True, None])
def test_source_restriction_or_missing_sql_decision_precedes_metadata_access(
    restricted: bool | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = Mock(spec=Session)
    session.scalar.side_effect = [3, restricted]
    session.scalars.return_value.all.return_value = [
        SimpleNamespace(kind="scenario", run_id=uid(10))
    ]
    auth = Mock(spec=ReportAuthorization)
    auth.owner_id, auth.account_id = uid(1), uid(2)
    metadata = Mock(side_effect=AssertionError("source authorization must precede metadata access"))
    monkeypatch.setattr(sources, "_scenario_metadata", metadata)
    with pytest.raises(AuthorizationError):
        sources.authorize_report_premium_sources(
            session, cast(ReportAuthorization, auth), input_id=uid(3), now=AT.value
        )
    metadata.assert_not_called()


def test_legacy_empty_lineage_needs_no_premium_metadata_lookup() -> None:
    session = Mock(spec=Session)
    session.scalar.return_value = 1
    session.scalars.return_value.all.return_value = []
    auth = Mock(spec=ReportAuthorization)
    auth.owner_id, auth.account_id = uid(1), uid(2)
    sources.authorize_report_premium_sources(
        session, cast(ReportAuthorization, auth), input_id=uid(3), now=AT.value
    )
    session.scalar.assert_called_once()
