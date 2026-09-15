"""Actual three-statement X-ray proof reads and original-rights boundary failures."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from trading212_application import research as app
from trading212_domain.research_facts import copy_research_portfolio_facts
from trading212_domain.sources import LicensePermission
from trading212_domain.xray_codec import decode_xray_result, encode_xray_result
from trading212_persistence import research_xray_read as module
from trading212_persistence.planning_models import AnalyticsRunModel
from trading212_persistence.research_source_store import research_owner_lock
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.xray_run_models import XrayRunModel
from trading212_worker.xray_seed import XRAY_CURSOR_KEY
from trading212_worker.xray_source_fixture import xray_license

from tests.integration.research_case import ResearchCase
from tests.integration.research_case import research_case as research_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


@contextmanager
def statements(case: ResearchCase) -> Iterator[list[str]]:
    captured: list[str] = []

    def receive(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        captured.append(statement)

    event.listen(case.xray.engine, "before_cursor_execute", receive)
    try:
        yield captured
    finally:
        event.remove(case.xray.engine, "before_cursor_execute", receive)


@pytest.mark.asyncio
async def test_actual_saved_finance_and_full_proof_use_exactly_three_statements(
    research_case: ResearchCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = research_case
    with case.xray.sessions() as session, session.begin():
        auth = case.auth(session)
        research_owner_lock(session, auth.owner_id)
        original = session.scalar(
            select(AnalyticsRunModel.canonical_result)
            .join(XrayRunModel, XrayRunModel.analytics_run_id == AnalyticsRunModel.id)
            .where(XrayRunModel.id == case.run_id, XrayRunModel.owner_id == auth.owner_id)
        )
        assert original is not None
        canonical = decode_xray_result(original)
        recompute = Mock(side_effect=AssertionError("research must never recalculate X-ray"))
        monkeypatch.setattr("trading212_analytics.xray.calculate_xray", recompute)
        with statements(case) as queries:
            basis = module.read_research_xray(session, auth, case.run_id, now=case.xray.now[0])
            module.finish_research_xray(session, auth, basis, now=case.xray.now[0])
        assert len(queries) == 3
        assert "WITH root AS MATERIALIZED" in queries[0]
        assert "WITH owned AS MATERIALIZED" in queries[1]
        assert "WITH root AS MATERIALIZED" in queries[2]
        assert basis.result == canonical
        assert encode_xray_result(basis.result) == original
        assert basis.result.terminal_paths == canonical.terminal_paths
        assert basis.result.typed_source_uses == canonical.typed_source_uses
        assert basis.result.source_dependencies == canonical.source_dependencies
        copied = copy_research_portfolio_facts(basis.pin, basis.result, case.entity_id)
        assert copied.effective_exposure is not None
        assert copied.effective_exposure.amount == Decimal("560")
        assert basis.pin.source_cutoff_at == canonical.source_cutoff_at.value
        assert basis.pin.valuation_at == canonical.valuation_at.value
        assert basis.deadline is not None and basis.deadline > case.xray.now[0]
        recompute.assert_not_called()
        auth.check(session, now=case.xray.now[0])
        assert (
            session.scalar(
                select(AnalyticsRunModel.canonical_result)
                .join(XrayRunModel, XrayRunModel.analytics_run_id == AnalyticsRunModel.id)
                .where(XrayRunModel.id == case.run_id)
            )
            == original
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ("owner_id", "account_id"))
async def test_foreign_identity_fails_in_metadata_without_private_fetch(
    research_case: ResearchCase,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    case = research_case
    decode = Mock(side_effect=AssertionError("foreign private payload"))
    monkeypatch.setattr(module, "decode_xray_input", decode)
    with case.xray.sessions() as session, session.begin():
        auth = case.auth(session)
        research_owner_lock(session, auth.owner_id)
        foreign = (
            replace(auth, owner_id=uuid4())
            if field == "owner_id"
            else replace(auth, account_id=uuid4())
        )
        with statements(case) as queries, pytest.raises(app.ResearchServiceError) as error:
            module.read_research_xray(session, foreign, case.run_id, now=case.xray.now[0])
        assert error.value.code is app.ResearchErrorCode.NOT_FOUND
        assert len(queries) == 1
        decode.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("restriction", ("store", "display", "original_lifetime"))
async def test_future_current_license_activation_is_checked_before_decode_and_at_finish(
    research_case: ResearchCase,
    monkeypatch: pytest.MonkeyPatch,
    restriction: str,
) -> None:
    case = research_case
    activation = case.xray.now[0] + timedelta(seconds=1)
    license = replace(
        xray_license(),
        id=str(uuid4()),
        version="research-future-restriction",
        effective_at=activation,
    )
    if restriction == "store":
        license = replace(license, store=LicensePermission.DENIED)
    elif restriction == "display":
        license = replace(license, display=LicensePermission.DENIED)
    else:
        license = replace(license, retention_days=1)
    service = PostgresSourceService(
        sessions=case.xray.sessions,
        cursor_signing_key=XRAY_CURSOR_KEY,
        clock=lambda: case.xray.now[0],
    )
    await service.register_source_license(
        case.xray.principal,
        license,
        idempotency_key="research-xray-future-license",
        correlation_id="research-xray-future-license",
    )
    with case.xray.sessions() as session, session.begin():
        auth = case.auth(session)
        research_owner_lock(session, auth.owner_id)
        with statements(case) as queries:
            basis = module.read_research_xray(session, auth, case.run_id, now=case.xray.now[0])
        assert len(queries) == 2
        # The policy becomes current in the same already-open transaction. Both
        # boundaries must use the new effective policy and original source age.
        case.xray.now[0] = activation + timedelta(seconds=1)
        decode = Mock(side_effect=AssertionError("denied private payload decoded"))
        monkeypatch.setattr(module, "decode_xray_input", decode)
        with statements(case) as queries, pytest.raises(app.ResearchServiceError) as error:
            module.finish_research_xray(session, auth, basis, now=case.xray.now[0])
        assert error.value.code is app.ResearchErrorCode.SOURCE_UNAVAILABLE
        assert len(queries) == 1
        with statements(case) as queries, pytest.raises(app.ResearchServiceError) as error:
            module.read_research_xray(session, auth, case.run_id, now=case.xray.now[0])
        assert error.value.code is app.ResearchErrorCode.SOURCE_UNAVAILABLE
        assert len(queries) == 1
        decode.assert_not_called()


@pytest.mark.asyncio
async def test_final_physical_child_membership_is_checked_against_actual_rows(
    research_case: ResearchCase,
) -> None:
    case = research_case
    with case.xray.sessions() as session, session.begin():
        auth = case.auth(session)
        research_owner_lock(session, auth.owner_id)
        basis = module.read_research_xray(session, auth, case.run_id, now=case.xray.now[0])
        physical = json.loads(basis._physical)
        child = next(row for row in physical if row["kind"] == "snapshot_position")
        child["record_id"] = str(uuid4())
        altered = replace(basis, _physical=json.dumps(physical, separators=(",", ":")))
        with statements(case) as queries, pytest.raises(app.ResearchServiceError) as error:
            module.finish_research_xray(session, auth, altered, now=case.xray.now[0])
        assert error.value.code is app.ResearchErrorCode.SOURCE_UNAVAILABLE
        assert len(queries) == 1
        # No database guard or original financial row was disabled or rewritten.
        module.finish_research_xray(session, auth, basis, now=case.xray.now[0])
