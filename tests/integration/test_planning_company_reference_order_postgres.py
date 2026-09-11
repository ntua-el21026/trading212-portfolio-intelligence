"""Real sealed X-ray runs keep company reads valid in either proof-reference order."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_domain.xray_codec import encode_xray_input
from trading212_persistence.planning_models import AnalyticsRunModel
from trading212_persistence.xray_capture import capture_xray
from trading212_persistence.xray_publication import publish_xray

from tests.integration.test_planning_company_postgres import request, service
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("descending", (False, True), ids=("ascending", "descending"))
def test_company_first_read_and_saved_drift_replay_accept_actual_reference_inventory(
    xray_read_case: XrayReadCase,
    descending: bool,
) -> None:
    async def run() -> None:
        case = xray_read_case

        def publish(session: Session, owner: UUID) -> str:
            captured = capture_xray(
                case.service,
                session,
                owner,
                UUID(case.seed["account_id"]),
                case.request(),
            )
            value = captured.value
            references = tuple(
                sorted(
                    value.portfolio_total.source_reference_ids,
                    key=str,
                    reverse=descending,
                )
            )
            assert len(references) == 2 and references[0] != references[1]
            total = replace(value.portfolio_total, source_reference_ids=references)
            # Change only an unordered reference tuple BEFORE normal publication/sealing.
            # Financial facts, source identities and actual physical bindings are unchanged.
            reordered = replace(
                value,
                portfolio_total=total,
                reconciliation=replace(value.reconciliation, declared_total=total),
            )
            canonical = encode_xray_input(reordered)
            assert canonical == captured.canonical_input
            stored = publish_xray(
                case.service,
                session,
                replace(captured, value=reordered, canonical_input=canonical),
            )
            return str(stored.id)

        run_id = await case.service._xrun(case.principal, publish)
        query = await request(case, None)
        base = await service(case).get_actual_vs_target(
            case.principal,
            case.seed["account_id"],
            query=query,
        )
        with case.sessions() as session:
            before = tuple(
                session.execute(
                    select(
                        AnalyticsRunModel.id,
                        AnalyticsRunModel.canonical_input,
                        AnalyticsRunModel.canonical_result,
                        AnalyticsRunModel.content_digest,
                    ).order_by(AnalyticsRunModel.id)
                ).all()
            )
        selected = replace(query, xray_run_id=run_id)
        # Each new service reads the original sealed bytes and the cached drift result.
        first = await service(case).get_actual_vs_target(
            case.principal,
            case.seed["account_id"],
            query=selected,
        )
        repeated = await service(case).get_actual_vs_target(
            case.principal,
            case.seed["account_id"],
            query=selected,
        )
        assert first.company_basis is not None
        assert first.content_digest == repeated.content_digest == base.content_digest
        assert first.company_basis == repeated.company_basis
        assert first.projection_digest == repeated.projection_digest
        assert first.rows.items == repeated.rows.items
        with case.sessions() as session:
            after = tuple(
                session.execute(
                    select(
                        AnalyticsRunModel.id,
                        AnalyticsRunModel.canonical_input,
                        AnalyticsRunModel.canonical_result,
                        AnalyticsRunModel.content_digest,
                    ).order_by(AnalyticsRunModel.id)
                ).all()
            )
        assert after == before

    asyncio.run(run())
