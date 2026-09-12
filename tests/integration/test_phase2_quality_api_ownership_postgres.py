"""Real API quality ownership cases for P210.

Complements the existing service-level invalid-account/current-grant cases and
mocked route tests. This is a narrow S32 slice, not the full API/MCP owner grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Never
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from trading212_api.main import create_app
from trading212_application import intelligence_quality as q
from trading212_persistence import PostgresPortfolioService
from trading212_persistence import intelligence_quality_service as implementation
from trading212_persistence.intelligence_quality_models import (
    IntelligenceQualityCollectionBindingModel,
    IntelligenceQualityCollectionSourceModel,
)
from trading212_persistence.models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    CollectionQuerySnapshotModel,
    OwnerModel,
    PrincipalModel,
)
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_security.principals import AuthenticationError, Principal, Scope
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_worker.historical_seed import CURSOR_KEY

from tests.integration.report_history_cases import HistoryReportCase
from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import seeded_history as seeded_history
from tests.integration.test_intelligence_quality_postgres import (
    SeededHistory,
    case_for,
    prepare_performance,
    protected_effects,
    read,
    service_for,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class QualityApiCase:
    case: HistoryReportCase
    api: FastAPI
    other_account_id: UUID
    cursor: str
    private_ids: tuple[str, ...]


class QualityBearer:
    def __init__(self, owner: Principal, other: Principal) -> None:
        self._principals = {"quality-owner": owner, "quality-other": other}

    async def authenticate(self, token: str) -> Principal:
        principal = self._principals.get(token)
        if principal is None:
            raise AuthenticationError("Authentication is required.")
        return principal


@pytest.fixture(scope="module")
def quality_api_case(seeded_history: SeededHistory) -> QualityApiCase:
    case = case_for(seeded_history)
    prepare_performance(case)
    now = datetime.now(UTC)
    quality = service_for(case, clock=lambda: now)
    retained = read(
        quality, case.principal, case.account_id, q.IntelligenceKind.PERFORMANCE, limit=1
    )
    assert isinstance(retained, q.IntelligenceDataQuality)
    assert retained.selection is not None
    assert retained.sources.next_cursor is not None
    other_owner, other_principal, connection, account = (uuid4() for _ in range(4))
    issuer, subject = "quality-grid", str(other_principal)
    with case.sessions() as session, session.begin():
        session.add(OwnerModel(id=other_owner, display_name="Quality second owner"))
        session.flush()
        session.add(
            PrincipalModel(
                id=other_principal,
                owner_id=other_owner,
                issuer=issuer,
                subject=subject,
                status="active",
                last_authenticated_at=now,
            )
        )
        session.add(
            BrokerConnectionModel(
                id=connection,
                owner_id=other_owner,
                provider="synthetic",
                environment="synthetic",
                credential_reference=None,
                status="active",
            )
        )
        session.flush()
        session.add(
            BrokerAccountModel(
                id=account,
                connection_id=connection,
                provider_account_id=str(account),
                account_type="synthetic",
                base_currency="EUR",
                display_name="Empty second account",
                status="active",
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        session.flush()
        provision_principal_scopes(
            session,
            principal_id=other_principal,
            scopes=frozenset(Scope),
            now=now - timedelta(seconds=1),
        )
    other = Principal(
        principal_id=str(other_principal),
        owner_id=str(other_owner),
        issuer=issuer,
        subject=subject,
        scopes=frozenset(Scope),
        authenticated_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(hours=1),
    )
    api = create_app(
        settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST,
            allowed_hosts=("testserver",),
        ),
        service=PostgresPortfolioService(
            sessions=case.sessions,
            cursor_signing_key=CURSOR_KEY,
            clock=lambda: now,
        ),
        intelligence_quality_service=quality,
        bearer_authenticator=QualityBearer(case.principal, other),
        clock=lambda: now,
    )
    return QualityApiCase(
        case,
        api,
        account,
        retained.sources.next_cursor,
        (
            str(case.account_id),
            str(case.principal.owner_id),
            str(retained.selection.id),
            retained.selection.content_digest,
            *(str(source.identity.id) for source in retained.sources.items),
        ),
    )


def retained_effects(case: HistoryReportCase) -> tuple[int | None, ...]:
    with case.sessions() as session:
        collections = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                CollectionQuerySnapshotModel,
                IntelligenceQualityCollectionBindingModel,
                IntelligenceQualityCollectionSourceModel,
            )
        )
    return (*protected_effects(case), *collections)


@pytest.mark.parametrize("kind", tuple(q.IntelligenceKind), ids=lambda kind: kind.value)
async def test_real_quality_api_denies_foreign_account_and_cursor_before_family_lookup(
    quality_api_case: QualityApiCase,
    monkeypatch: pytest.MonkeyPatch,
    kind: q.IntelligenceKind,
) -> None:
    case = quality_api_case
    route = "/api/v1/accounts/{}/intelligence-data-quality"
    headers = {"Authorization": "Bearer quality-other", "If-None-Match": "*"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(case.api),
        base_url="https://testserver",
    ) as client:
        # Both principals pass the actual factory and persistence authorization.
        owner = await client.get(
            route.format(case.case.account_id),
            params={"analytics_kind": "performance", "limit": 1},
            headers={"Authorization": "Bearer quality-owner"},
        )
        assert owner.status_code == 200 and owner.json()["selection_state"] == "retained"
        other = await client.get(
            route.format(case.other_account_id),
            params={"analytics_kind": kind.value, "limit": 1},
            headers=headers,
        )
        assert other.status_code == 200
        assert other.json()["account_id"] == str(case.other_account_id)
        assert other.json()["selection_state"] == "not_available"
        before = retained_effects(case.case)

        def forbidden_selection(*args: object, **kwargs: object) -> Never:
            pytest.fail("unauthorized quality family lookup")

        monkeypatch.setattr(implementation, "select_retained", forbidden_selection)
        for account, cursor in (
            (case.case.account_id, None),
            (case.case.account_id, case.cursor),
            (uuid4(), None),
        ):
            query: dict[str, str | int] = {"analytics_kind": kind.value, "limit": 1}
            if cursor is not None:
                query["cursor"] = cursor
            denied = await client.get(route.format(account), params=query, headers=headers)
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "ACCESS_DENIED"
            assert "etag" not in denied.headers
            assert all(value not in denied.text for value in (*case.private_ids, case.cursor))
            assert "quality-other" not in denied.text
        # An authorized second owner's own account cannot resume the first owner's
        # collection either. Cursor binding must reject before selecting a family.
        wrong_collection = await client.get(
            route.format(case.other_account_id),
            params={"analytics_kind": "performance", "limit": 1, "cursor": case.cursor},
            headers=headers,
        )
        assert wrong_collection.status_code == 422
        assert wrong_collection.json()["error"]["code"] == "INVALID_CURSOR"
        assert all(value not in wrong_collection.text for value in (*case.private_ids, case.cursor))
        assert retained_effects(case.case) == before
