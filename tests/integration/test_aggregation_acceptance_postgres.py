"""Independent small-fixture aggregation admission, ambiguity and atomicity proofs."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from trading212_application import aggregation as app
from trading212_application import aggregation_views as views
from trading212_domain import CurrencyCode
from trading212_domain.aggregation import (
    AggregateActivityWindow,
    AggregateFxBinding,
    AggregateMember,
    AggregateReason,
    AggregateSelectionContent,
    AggregateView,
)
from trading212_persistence import aggregation_models as m
from trading212_persistence.aggregation_authorization import AggregateAuthorization
from trading212_persistence.aggregation_service import PostgresAggregateService
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_security.principals import Scope
from trading212_worker.synthetic_custody_types import CustodyActivity, CustodyTransferEvidence
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from scripts.api_e2e_aggregation import (
    EUR_ACCOUNT_ID,
    USD_ACCOUNT_ID,
    seed_aggregation_browser_scenario,
)
from tests.integration.aggregation_acceptance_fixtures import (
    native_selection,
    original_sources,
    publication_state,
)
from tests.integration.test_aggregation_postgres import command, prepared, statements
from tests.integration.test_xray_reads_postgres import XrayReadCase
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


async def test_eight_owned_native_members_publish_one_economic_holding_with_exact_contributions(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    service, selected = await native_selection(case, member_count=8)
    accounts = tuple(member.account_id for member in selected.content.members)
    before = original_sources(case, accounts)
    request = command(selected)
    run = await service.create_run(case.principal, request)
    saved = await service.get_run(case.principal, run.run_id, app.AggregateRunQuery())
    assert isinstance(saved.page, views.AggregateHoldingPage)
    assert len(saved.page.context.snapshots) == 8
    assert tuple(pin.account_id for pin in saved.page.context.snapshots) == accounts
    assert saved.page.context.total.value == Decimal("1987450.16")
    assert saved.page.context.securities.value == Decimal("1888000")
    assert saved.page.context.cash.value == Decimal("99450.16")
    assert saved.page.context.rounding_residual == Decimal("0")
    assert saved.page.total == 1 and len(saved.page.items) == 1
    holding = saved.page.items[0]
    assert holding.quantity == Decimal("3200")
    assert holding.money.value == Decimal("1888000")
    assert tuple(row.account_id for row in holding.account_totals) == accounts
    assert [row.money.value for row in holding.account_totals] == [Decimal("236000")] * 8
    assert await service.create_run(case.principal, request) == run
    assert original_sources(case, accounts) == before
    current = await service.get_selection(case.principal, selected.selection_id)
    assert current.content == selected.content and current.content_digest == selected.content_digest
    assert current.revision == selected.revision + 1


def _counterpart_activity(
    mode: str,
    accounts: tuple[UUID, ...],
    index: int,
    now: datetime,
) -> tuple[CustodyActivity, ...]:
    at = now - timedelta(hours=1)
    if index == 1 and mode == "missing":
        return ()
    amount = Decimal("-100" if index == 0 else "99" if mode == "principal" else "100")
    reference = "other-original-reference" if mode == "reference" and index == 1 else "pair"
    leg = CustodyActivity(
        native_record_key="transfer-1",
        kind="custody_transfer",
        booked_at=at,
        published_at=at,
        signed_cash=amount,
        currency=CurrencyCode("EUR"),
        transfer=CustodyTransferEvidence(
            counterparty_account_id=accounts[1 - index],
            transfer_reference=reference,
            principal=amount,
            currency=CurrencyCode("EUR"),
        ),
    )
    if mode == "ambiguous" and index == 1:
        return leg, replace(leg, native_record_key="transfer-2")
    return (leg,)


@pytest.mark.parametrize(
    ("mode", "count", "classification", "reason"),
    (
        ("ambiguous", 3, "ambiguous_transfer", AggregateReason.AMBIGUOUS_TRANSFER),
        ("missing", 1, "unmatched_transfer", AggregateReason.UNMATCHED_TRANSFER),
        ("reference", 2, "unmatched_transfer", AggregateReason.UNMATCHED_TRANSFER),
        ("principal", 2, "unmatched_transfer", AggregateReason.TRANSFER_PROOF_INCOMPLETE),
    ),
)
async def test_original_counterpart_ambiguity_or_missing_proof_never_cancels_cash(
    xray_read_case: XrayReadCase,
    mode: str,
    count: int,
    classification: str,
    reason: AggregateReason,
) -> None:
    case = xray_read_case
    service, selected = await native_selection(
        case,
        activities=lambda accounts, index, now: _counterpart_activity(mode, accounts, index, now),
    )
    accounts = tuple(member.account_id for member in selected.content.members)
    before = original_sources(case, accounts)
    request = replace(
        command(selected),
        activity_window=AggregateActivityWindow(
            start_at=case.now[0] - timedelta(days=1), end_at=case.now[0]
        ),
    )
    run = await service.create_run(case.principal, request)
    actual = await service.get_run(
        case.principal, run.run_id, app.AggregateRunQuery(view=AggregateView.TRANSFERS)
    )
    assert isinstance(actual.page, views.AggregateTransferPage)
    assert actual.page.total == count and len(actual.page.items) == count
    assert actual.page.candidate_count == count and actual.page.selected_count == count
    assert {row.leg.classification for row in actual.page.items} == {classification}
    assert {row.leg.reason for row in actual.page.items} == {reason}
    assert all(
        row.match is None and row.leg.counterpart_record_id is None for row in actual.page.items
    )
    assert set(actual.page.reasons) == {reason, AggregateReason.COVERAGE_INCOMPLETE}
    assert not actual.page.complete and actual.page.currency_totals == ()
    holdings = await service.get_run(case.principal, run.run_id, app.AggregateRunQuery())
    assert isinstance(holdings.page, views.AggregateHoldingPage)
    assert holdings.page.context.total.value == Decimal("496862.54")
    assert original_sources(case, accounts) == before
    assert await service.create_run(case.principal, request) == run


async def test_omitted_activity_reads_no_activity_sources_and_discloses_not_requested(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    service, selected = await native_selection(case)
    with statements(case) as captured:
        run = await service.create_run(case.principal, command(selected))
    # Position/cash provenance may inspect source headers; no private activity body or
    # revision/coverage capture is needed when no activity window was requested.
    assert not any("source_records.sanitized_payload" in sql for sql in captured)
    assert not any("FROM activity_revision_evidence" in sql for sql in captured)
    actual = await service.get_run(
        case.principal, run.run_id, app.AggregateRunQuery(view=AggregateView.TRANSFERS)
    )
    assert isinstance(actual.page, views.AggregateTransferPage)
    assert actual.page.reasons == (AggregateReason.NOT_REQUESTED,)
    assert not actual.page.complete and actual.page.items == ()
    assert actual.page.window is None and actual.page.candidate_count == 0
    with case.sessions() as session:
        assert (
            session.scalar(select(func.count()).select_from(m.AggregateActivityPayloadModel)) == 0
        )
        assert (
            session.scalar(select(func.count()).select_from(m.AggregateActivityEvidenceModel)) == 0
        )


async def test_real_selection_capacity_admits_512_then_rejects_without_command_or_charge(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    service, selected = await native_selection(case)
    # Populate the bounded definition inventory through normal admission. No owner
    # counter is forged and no large financial payload is allocated for this edge.
    for index in range(511):
        await service.create_selection(
            case.principal,
            app.CreateAggregateSelection(
                content=replace(selected.content, name=f"Retained selection {index + 2}"),
                idempotency_key=str(uuid4()),
                correlation_id="aggregation-definition-capacity",
            ),
        )
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(m.AggregateSelectionModel)) == 512
        assert (
            session.scalar(
                text(
                    "SELECT definition_versions FROM premium_owner_capacity WHERE owner_id=:owner"
                ),
                {"owner": UUID(case.principal.owner_id)},
            )
            == 512
        )
    before = publication_state(case)
    with pytest.raises(app.AggregateServiceError) as denied:
        await service.create_selection(
            case.principal,
            app.CreateAggregateSelection(
                content=replace(selected.content, name="Rejected 513th selection"),
                idempotency_key=str(uuid4()),
                correlation_id="aggregation-definition-capacity",
            ),
        )
    assert denied.value.code is app.AggregateErrorCode.RATE_LIMITED
    assert publication_state(case) == before
    # Capacity does not erase the immutable receipt or existing owned selection.
    assert await service.get_selection(case.principal, selected.selection_id) == selected


async def test_missing_then_explicit_saved_fx_preserves_native_facts_and_exact_totals(
    xray_read_case: XrayReadCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = xray_read_case
    case.now[0] = datetime.now(UTC).replace(microsecond=0)
    monkeypatch.setenv("T212PI_E2E_AGGREGATION", "1")
    metadata = await seed_aggregation_browser_scenario(
        case.sessions, app_environment="test", at=case.now[0]
    )
    service = PostgresAggregateService(
        case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: case.now[0]
    )
    selected = await service.create_selection(
        case.principal,
        app.CreateAggregateSelection(
            content=AggregateSelectionContent(
                name="Native EUR and USD with explicit retained FX",
                members=(
                    AggregateMember(
                        account_id=EUR_ACCOUNT_ID,
                        portfolio_snapshot_id=UUID(metadata["eur_snapshot_id"]),
                    ),
                    AggregateMember(
                        account_id=USD_ACCOUNT_ID,
                        portfolio_snapshot_id=UUID(metadata["usd_snapshot_id"]),
                    ),
                ),
                reporting_currency=CurrencyCode("EUR"),
                source_cutoff_at=case.now[0],
            ),
            idempotency_key=str(uuid4()),
            correlation_id="aggregation-fx-acceptance",
        ),
    )
    sources = original_sources(case, (EUR_ACCOUNT_ID, USD_ACCOUNT_ID))
    missing = await service.create_run(case.principal, command(selected))
    partial = await service.get_run(
        case.principal, missing.run_id, app.AggregateRunQuery(view=AggregateView.COMPONENTS)
    )
    assert isinstance(partial.page, views.AggregateComponentPage)
    assert partial.page.context.total.value is None
    assert partial.page.context.total.known_value == Decimal("248431.27")
    assert partial.page.context.total.reason is AggregateReason.FX_MISSING
    usd_rows = tuple(row for row in partial.page.items if row.native.account_id == USD_ACCOUNT_ID)
    assert {row.native.native_value for row in usd_rows} == {Decimal("150"), Decimal("30")}
    assert all(row.converted_value is None for row in usd_rows)
    current = await service.get_selection(case.principal, selected.selection_id)
    binding = AggregateFxBinding(
        account_id=USD_ACCOUNT_ID,
        currency=CurrencyCode("USD"),
        fx_observation_id=UUID(metadata["fx_observation_id"]),
    )
    before_invalid = publication_state(case)
    for invalid, expected in (
        (replace(binding, fx_observation_id=uuid4()), app.AggregateErrorCode.SOURCE_UNAVAILABLE),
        (replace(binding, account_id=uuid4()), app.AggregateErrorCode.SOURCE_UNAVAILABLE),
        (replace(binding, currency=CurrencyCode("GBP")), app.AggregateErrorCode.VALIDATION_FAILED),
    ):
        with pytest.raises(app.AggregateServiceError) as denied:
            await service.create_run(
                case.principal, replace(command(current), fx_bindings=(invalid,))
            )
        assert denied.value.code is expected
        assert publication_state(case) == before_invalid
    request = replace(
        command(current),
        fx_bindings=(binding,),
    )
    complete = await service.create_run(case.principal, request)
    result = await service.get_run(case.principal, complete.run_id, app.AggregateRunQuery())
    assert isinstance(result.page, views.AggregateHoldingPage)
    assert result.page.context.total.value == Decimal("248575.27")
    assert result.page.context.securities.value == Decimal("236120")
    assert result.page.context.cash.value == Decimal("12455.27")
    assert result.page.context.rounding_residual == Decimal("0")
    assert len(result.page.items) == 1 and result.page.items[0].quantity == Decimal("403")
    assert {row.account_id: row.money.value for row in result.page.items[0].account_totals} == {
        EUR_ACCOUNT_ID: Decimal("236000"),
        USD_ACCOUNT_ID: Decimal("120"),
    }
    assert original_sources(case, (EUR_ACCOUNT_ID, USD_ACCOUNT_ID)) == sources
    assert await service.create_run(case.principal, request) == complete
    unchanged = await service.get_run(
        case.principal, missing.run_id, app.AggregateRunQuery(view=AggregateView.COMPONENTS)
    )
    assert unchanged == partial


async def test_current_read_grant_revocation_precedes_cursor_and_private_projection_reads(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    service, selected = await prepared(case)
    request = command(selected)
    run = await service.create_run(case.principal, request)
    with case.sessions.begin() as session:
        session.execute(
            update(PrincipalScopeGrantModel)
            .where(PrincipalScopeGrantModel.scope == Scope.AGGREGATE_READ.value)
            .values(revoked_at=case.now[0])
        )
    before = publication_state(case)
    with statements(case) as captured, pytest.raises(app.AggregateServiceError) as denied:
        await service.get_run(
            case.principal,
            run.run_id,
            app.AggregateRunQuery(view=AggregateView.COMPONENTS, cursor="invalid-signed-cursor"),
        )
    assert denied.value.code is app.AggregateErrorCode.ACCESS_DENIED
    assert not any(
        "summary_payload" in sql or "aggregate_components.payload" in sql for sql in captured
    )
    with pytest.raises(app.AggregateServiceError) as replay:
        await service.create_run(case.principal, request)
    assert replay.value.code is app.AggregateErrorCode.ACCESS_DENIED
    assert publication_state(case) == before


async def test_final_authorization_denial_rolls_back_published_copies_capacity_and_receipt(
    xray_read_case: XrayReadCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = xray_read_case
    service, selected = await prepared(case)
    request = command(selected)
    before = publication_state(case)
    finish = AggregateAuthorization.finish
    reached = []

    def revoke_after_publication(
        auth: AggregateAuthorization, session: Session, *, now: datetime
    ) -> None:
        if session.scalar(select(func.count()).select_from(m.AggregateHoldingsPayloadModel)):
            reached.append(True)
            session.execute(
                update(PrincipalScopeGrantModel)
                .where(
                    PrincipalScopeGrantModel.principal_id == auth.principal_id,
                    PrincipalScopeGrantModel.scope == Scope.AGGREGATE_READ.value,
                )
                .values(revoked_at=now)
            )
        finish(auth, session, now=now)

    with monkeypatch.context() as fault:
        fault.setattr(AggregateAuthorization, "finish", revoke_after_publication)
        with pytest.raises(app.AggregateServiceError) as denied:
            await service.create_run(case.principal, request)
    assert reached == [True]
    assert denied.value.code is app.AggregateErrorCode.ACCESS_DENIED
    assert publication_state(case) == before
    # The failed transaction also rolls back the injected grant change. Reusing the
    # original semantic key must create one complete result with no stale receipt.
    run = await service.create_run(case.principal, request)
    assert await service.create_run(case.principal, request) == run
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(m.AggregateRunModel)) == 1
        assert session.scalar(text("SELECT aggregate_run_complete(:run)"), {"run": run.run_id})


@pytest.mark.parametrize("field", ("reserved_bytes", "retained_bytes", "financial_rows"))
async def test_published_capacity_counter_forgery_is_rejected_without_state_change(
    xray_read_case: XrayReadCase, field: str
) -> None:
    case = xray_read_case
    service, selected = await prepared(case)
    run = await service.create_run(case.principal, command(selected))
    before = publication_state(case)
    with (
        case.sessions.begin() as session,
        pytest.raises(IntegrityError, match="aggregate root is immutable"),
        session.begin_nested(),
    ):
        session.execute(
            update(m.AggregateRunModel)
            .where(m.AggregateRunModel.id == run.run_id)
            .values({field: 1})
        )
    assert publication_state(case) == before
    actual = await service.get_run(case.principal, run.run_id, app.AggregateRunQuery())
    assert isinstance(actual.page, views.AggregateHoldingPage)
    assert actual.page.context.total.value == Decimal("496862.54")
