"""The frozen 32MiB X-ray ceiling changes no other analytical storage limit."""

from typing import cast

import pytest
from sqlalchemy import CheckConstraint, Table
from trading212_persistence.planning_models import AnalyticsRunModel


@pytest.mark.parametrize("column", ("canonical_input", "canonical_result"))
def test_xray_analytics_metadata_matches_frozen_canonical_limit(column: str) -> None:
    checks = {
        str(check.name): str(check.sqltext)
        for check in cast(Table, AnalyticsRunModel.__table__).constraints
        if isinstance(check, CheckConstraint)
    }
    assert checks[f"ck_analytics_runs_bound_{column}"] == (
        f"octet_length({column}) <= "
        "CASE WHEN kind IN ('performance','benchmark','income','attribution','cash_flow','xray') "
        "THEN 33554432 ELSE 8388608 END"
    )
