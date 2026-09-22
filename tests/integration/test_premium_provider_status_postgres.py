"""Real current authority and whole-request SQL ceiling; no provider calls."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import event, select, update
from trading212_application import premium_provider_status as app
from trading212_persistence.acquisition_authority import grant_digest
from trading212_persistence.acquisition_models import ProviderCapabilityGrantModel
from trading212_persistence.models import PrincipalModel
from trading212_persistence.premium_provider_status import PostgresPremiumProviderStatusService
from trading212_persistence.report_models import PrincipalScopeGrantModel
from trading212_security.principals import Scope

from tests.integration.provider_acquisition_case import acquisition_case
from tests.integration.test_xray_reads_postgres import (
    XrayReadCase,
)
from tests.integration.test_xray_reads_postgres import (
    xray_read_case as xray_read_case,
)

pytestmark = pytest.mark.integration
CONFIG = app.PremiumProviderConfiguration(
    outbound_enabled=True, alpha_vantage_credential_port_configured=True
)


@pytest.mark.asyncio
async def test_status_queries_are_bounded_and_do_not_select_private_source_data(
    xray_read_case: XrayReadCase,
) -> None:
    case = acquisition_case(xray_read_case)
    statements: list[str] = []

    def before(*args: Any) -> None:
        statements.append(str(args[2]))

    service = PostgresPremiumProviderStatusService(case.xray.sessions, configuration=CONFIG)
    event.listen(case.xray.engine, "before_cursor_execute", before)
    try:
        value = await service.get_premium_provider_status(
            case.xray.principal, case.selection.account_id
        )
    finally:
        event.remove(case.xray.engine, "before_cursor_execute", before)
    assert len(statements) <= 12
    assert len(value.providers) == 2 and tuple(len(x.capabilities) for x in value.providers) == (
        4,
        1,
    )
    daily = value.providers[0].capabilities[0]
    assert daily.state is app.PremiumReadiness.READY_UNVERIFIED and daily.daily_allowance == 25
    assert value.credential_verification == value.live_verification == "unavailable"
    assert not any(
        name in sql.lower()
        for sql in statements
        for name in (
            "price_observations",
            "fx_observations",
            "research_source_payloads",
            "canonical_payload",
            "encrypted_secret",
        )
    )
    no_research = replace(
        case.xray.principal, scopes=case.xray.principal.scopes - {Scope.RESEARCH_READ}
    )
    hidden = await service.get_premium_provider_status(no_research, case.selection.account_id)
    assert all(
        item.reason is app.PremiumStatusReason.RESEARCH_SCOPE_REQUIRED
        and item.daily_allowance is None
        for item in hidden.providers[0].capabilities[2:]
    )


@pytest.mark.asyncio
async def test_status_reloads_current_grants_and_rejects_foreign_accounts(
    xray_read_case: XrayReadCase,
) -> None:
    case = acquisition_case(xray_read_case)
    service = PostgresPremiumProviderStatusService(case.xray.sessions, configuration=CONFIG)
    with case.xray.sessions() as session, session.begin():
        old = case.grant
        grant = ProviderCapabilityGrantModel(
            id=uuid4(),
            owner_id=old.owner_id,
            provider_id=old.provider_id,
            scope_id=old.scope_id,
            version_number=2,
            license_version_id=old.license_version_id,
            effective_at=datetime.now(UTC),
            expires_at=old.expires_at,
            store_allowed=True,
            display_allowed=False,
            report_allowed=old.report_allowed,
            export_allowed=old.export_allowed,
            daily_allowance=old.daily_allowance,
            evidence_key="synthetic-current-revocation",
            content_digest="0" * 64,
            created_at=datetime.now(UTC),
        )
        grant.content_digest = grant_digest(grant)
        session.add(grant)
    value = await service.get_premium_provider_status(
        case.xray.principal, case.selection.account_id
    )
    assert (
        value.providers[0].capabilities[0].reason
        is app.PremiumStatusReason.CAPABILITY_RIGHTS_REQUIRED
    )
    with pytest.raises(app.PremiumStatusError) as failure:
        await service.get_premium_provider_status(case.xray.principal, uuid4())
    assert failure.value.code is app.PremiumStatusErrorCode.ACCESS_DENIED
    with case.xray.sessions() as session, session.begin():
        principal = session.scalar(
            select(PrincipalModel.id).where(
                PrincipalModel.issuer == case.xray.principal.issuer,
                PrincipalModel.subject == case.xray.principal.subject,
            )
        )
        session.execute(
            update(PrincipalScopeGrantModel)
            .where(
                PrincipalScopeGrantModel.principal_id == principal,
                PrincipalScopeGrantModel.scope == Scope.ANALYTICS_READ.value,
            )
            .values(revoked_at=datetime.now(UTC))
        )
    with pytest.raises(app.PremiumStatusError) as failure:
        await service.get_premium_provider_status(case.xray.principal, case.selection.account_id)
    assert failure.value.code is app.PremiumStatusErrorCode.ACCESS_DENIED


@pytest.mark.asyncio
async def test_final_projection_cannot_return_grant_metadata_after_clock_expiry(
    xray_read_case: XrayReadCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = acquisition_case(xray_read_case)
    now = [datetime.now(UTC)]
    service = PostgresPremiumProviderStatusService(
        case.xray.sessions, configuration=CONFIG, clock=lambda: now[0]
    )
    original = service._projection

    def project(*args: Any, **kwargs: Any) -> app.PremiumProviderStatusView:
        result = original(*args, **kwargs)
        now[0] = case.grant.expires_at + timedelta(seconds=1)
        return result

    monkeypatch.setattr(service, "_projection", project)
    value = await service.get_premium_provider_status(
        case.xray.principal, case.selection.account_id
    )
    assert value.observed_at > case.grant.expires_at
    assert value.providers[0].capabilities[0].state is app.PremiumReadiness.BLOCKED_EXTERNAL
    assert value.providers[0].capabilities[0].attempts_charged is None
