"""PostgreSQL authorization, retained quality results and stable source pages."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Set
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import historical as history
from trading212_application import intelligence_quality as q
from trading212_application.queries import CollectionSnapshotCapacityError, CursorValidationError
from trading212_domain import historical_results as results
from trading212_domain.historical import HistoricalGrouping
from trading212_domain.serialization import canonical_json
from trading212_domain.sources import LicensePermission, SourceLicense
from trading212_persistence import historical_models as hm
from trading212_persistence import intelligence_quality_service as implementation
from trading212_persistence.historical_service import PostgresHistoricalService
from trading212_persistence.intelligence_quality_models import (
    IntelligenceQualityCollectionBindingModel as Binding,
)
from trading212_persistence.intelligence_quality_models import (
    IntelligenceQualityCollectionSourceModel as Member,
)
from trading212_persistence.intelligence_quality_service import (
    BASE_SCOPES,
    PostgresIntelligenceDataQualityService,
)
from trading212_persistence.models import (
    BrokerAccountModel,
    CalculationRunModel,
    CollectionQuerySnapshotModel,
    PortfolioSnapshotModel,
    PrincipalModel,
    SnapshotCashModel,
)
from trading212_persistence.planning_models import AnalyticsRunModel
from trading212_persistence.principal_grants import provision_principal_scopes
from trading212_persistence.provider_observation_models import ProviderInvocationObservationModel
from trading212_persistence.source_models import ProviderLicenseVersionModel
from trading212_persistence.source_service import PostgresSourceService
from trading212_persistence.source_store import license_view
from trading212_security.principals import AuthorizationError, Principal, Scope
from trading212_worker.historical_seed import CURSOR_KEY

from tests.integration.report_history_cases import HistoryReportCase, history_report_case
from tests.integration.test_historical_postgres import historical_database as historical_database
from tests.integration.test_historical_seed import seeded_history as seeded_history
from tests.integration.test_historical_seed import window

pytestmark = pytest.mark.integration

type SeededHistory = tuple[sessionmaker[Session], dict[str, str]]


def case_for(seeded_history: SeededHistory) -> HistoryReportCase:
    sessions, identifiers = seeded_history
    return history_report_case(sessions, identifiers)


def provision(case: HistoryReportCase, scopes: Set[Scope]) -> Principal:
    with case.sessions() as session, session.begin():
        provision_principal_scopes(
            session,
            principal_id=UUID(case.principal.principal_id),
            scopes=frozenset(scopes),
            now=datetime.now(UTC),
        )
    return replace(case.principal, scopes=frozenset(scopes))


def read(
    service: q.IntelligenceDataQualityService,
    principal: Principal,
    account: UUID,
    kind: q.IntelligenceKind = q.IntelligenceKind.VALUATION,
    *,
    cursor: str | None = None,
    limit: int = 25,
) -> q.IntelligenceQualityResult:
    return asyncio.run(
        service.get_intelligence_data_quality(
            principal,
            str(account),
            query=q.IntelligenceDataQualityQuery(analytics_kind=kind, cursor=cursor, limit=limit),
        )
    )


def service_for(
    case: HistoryReportCase,
    *,
    clock: Callable[[], datetime] | None = None,
    max_active_collection_members_per_owner: int = 250_000,
) -> PostgresIntelligenceDataQualityService:
    return PostgresIntelligenceDataQualityService(
        case.sessions,
        cursor_signing_key=CURSOR_KEY,
        clock=clock,
        max_active_collection_members_per_owner=max_active_collection_members_per_owner,
    )


def prepare_performance(case: HistoryReportCase) -> history.PerformanceIntelligenceView:
    producer = PostgresHistoricalService(case.sessions, cursor_signing_key=CURSOR_KEY)
    return asyncio.run(
        producer.get_performance_summary(
            case.principal,
            str(case.account_id),
            query=history.PerformanceSummaryQuery(
                window=window("annual"), options=results.PerformanceOptions()
            ),
        )
    )


def protected_effects(case: HistoryReportCase) -> tuple[int | None, ...]:
    with case.sessions() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                AnalyticsRunModel,
                hm.HistoricalInputModel,
                hm.HistoricalRunModel,
                ProviderInvocationObservationModel,
            )
        )


def test_retained_performance_summary_uses_baseline_grants_without_activity_decode(
    seeded_history: SeededHistory, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = case_for(seeded_history)
    native = prepare_performance(case)
    principal = provision(case, BASE_SCOPES)
    before = protected_effects(case)
    statements: list[str] = []

    def sql_before(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    # An application decoder for the historical INPUT must never be used by this GET.
    import trading212_domain.historical_serialization as serialization

    monkeypatch.setattr(
        serialization, "historical_input_from_json", lambda *args: pytest.fail("input decoded")
    )
    engine = case.sessions.kw["bind"]
    event.listen(engine, "before_cursor_execute", sql_before)
    try:
        actual = read(service_for(case), principal, case.account_id, q.IntelligenceKind.PERFORMANCE)
    finally:
        event.remove(engine, "before_cursor_execute", sql_before)
    assert isinstance(actual, q.IntelligenceDataQuality)
    assert actual.selection_state == "retained" and actual.selection is not None
    assert actual.selection.content_digest == native.context.content_digest
    assert actual.selection.input_digest == native.context.input_digest
    assert actual.activity_visibility == actual.reconciliation.visibility == "permission_required"
    assert all(
        source.identity.kind
        not in {
            q.QualitySourceKind.BROKER_RECORD,
            q.QualitySourceKind.BROKER_OCCURRENCE,
            q.QualitySourceKind.RECONCILIATION,
            q.QualitySourceKind.REVISION,
        }
        for source in actual.sources.items
    )
    assert "canonical_input" not in " ".join(statements)
    assert protected_effects(case) == before
    for row in actual.metrics:
        native_metric = getattr(native.summary, row.key)
        assert row.recorded_availability is not None and row.recorded_quality is not None
        assert row.recorded_availability.value == native_metric.availability.value
        assert row.recorded_quality.value == native_metric.quality.value


@pytest.mark.parametrize(
    ("kind", "missing"),
    (
        (q.IntelligenceKind.INCOME, Scope.ACTIVITY_READ),
        (q.IntelligenceKind.CASH_FLOW, Scope.ACTIVITY_READ),
        (q.IntelligenceKind.ACTUAL_VS_TARGET, Scope.TARGETS_READ),
        (q.IntelligenceKind.DRIFT, Scope.TARGETS_READ),
    ),
)
def test_material_scope_permission_branch_precedes_every_family_lookup(
    seeded_history: SeededHistory,
    monkeypatch: pytest.MonkeyPatch,
    kind: q.IntelligenceKind,
    missing: Scope,
) -> None:
    case = case_for(seeded_history)
    principal = provision(case, BASE_SCOPES)
    monkeypatch.setattr(
        implementation,
        "select_retained",
        lambda *args, **kwargs: pytest.fail("family lookup before grant"),
    )
    actual = read(service_for(case), principal, case.account_id, kind, cursor="invalid-cursor")
    assert (
        isinstance(actual, q.IntelligenceQualityPermissionRequired)
        and actual.missing_scope is missing
    )
    assert set(json.loads(canonical_json(actual))) == {
        "state",
        "account_id",
        "analytics_kind",
        "checked_at",
        "missing_scope",
        "supported_kinds",
    }


@pytest.mark.parametrize(
    "failure", ("revoked", "principal_inactive", "account_inactive", "foreign_account")
)
def test_durable_authority_fails_before_selection_or_decode(
    seeded_history: SeededHistory, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    case = case_for(seeded_history)
    monkeypatch.setattr(
        implementation,
        "select_retained",
        lambda *args, **kwargs: pytest.fail("unauthorized selection"),
    )
    account = case.account_id
    if failure == "revoked":
        provision(case, {Scope.PORTFOLIO_READ})
    elif failure == "foreign_account":
        account = uuid4()
    else:
        model = PrincipalModel if failure == "principal_inactive" else BrokerAccountModel
        identifier = (
            UUID(case.principal.principal_id) if model is PrincipalModel else case.account_id
        )
        with case.sessions() as session, session.begin():
            session.execute(update(model).where(model.id == identifier).values(status="disabled"))
    try:
        with pytest.raises(AuthorizationError):
            read(service_for(case), case.principal, account)
    finally:
        if failure in {"principal_inactive", "account_inactive"}:
            with case.sessions() as session, session.begin():
                session.execute(update(model).where(model.id == identifier).values(status="active"))


def test_current_source_expiry_blocks_before_result_parser_even_for_baseline_read(
    seeded_history: SeededHistory, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = case_for(seeded_history)
    prepare_performance(case)
    principal = provision(case, BASE_SCOPES)
    first = read(
        service_for(case), principal, case.account_id, q.IntelligenceKind.PERFORMANCE, limit=100
    )
    assert isinstance(first, q.IntelligenceDataQuality)
    expires = [source.expires_at for source in first.sources.items if source.expires_at is not None]
    assert expires, "Fixture must contain an actual retained licensed physical source."
    at = min(expires) + timedelta(microseconds=1)
    principal = replace(principal, expires_at=at + timedelta(hours=1))
    monkeypatch.setattr(
        implementation, "decode_metrics", lambda *args: pytest.fail("decoded after source expiry")
    )
    actual = read(
        service_for(case, clock=lambda: at),
        principal,
        case.account_id,
        q.IntelligenceKind.PERFORMANCE,
    )
    assert isinstance(actual, q.IntelligenceDataQuality)
    assert actual.selection == first.selection and actual.selection_state == "unavailable"
    assert all(
        row.recorded_quality is None and row.current_usability == "blocked"
        for row in actual.metrics
    )


def test_target_bearing_attribution_is_filtered_before_baseline_selection(
    seeded_history: SeededHistory,
) -> None:
    case = case_for(seeded_history)
    producer = PostgresHistoricalService(case.sessions, cursor_signing_key=CURSOR_KEY)
    ungrouped = asyncio.run(
        producer.get_attribution_summary(
            case.principal,
            str(case.account_id),
            query=history.AttributionQuery(window=window("annual")),
        )
    )
    grouped = asyncio.run(
        producer.get_attribution_summary(
            case.principal,
            str(case.account_id),
            query=history.AttributionQuery(
                window=window("annual"),
                target_version_id=str(case.target_version_id),
                grouping_policy="explicit_comparison",
                options=results.AttributionOptions(grouping=HistoricalGrouping.GROUP),
            ),
        )
    )
    assert grouped.context.input_snapshot_id != ungrouped.context.input_snapshot_id
    with case.sessions() as session:
        expected = session.get_one(
            hm.HistoricalRunModel, UUID(ungrouped.context.run_id)
        ).analytics_run_id
    baseline = provision(case, BASE_SCOPES)
    actual = read(service_for(case), baseline, case.account_id, q.IntelligenceKind.ATTRIBUTION)
    assert isinstance(actual, q.IntelligenceDataQuality) and actual.selection is not None
    assert actual.selection.id == expected
    assert (
        actual.targets_visibility == "permission_required" and actual.selection_state == "retained"
    )
    assert all(
        source.identity.kind is not q.QualitySourceKind.TARGET for source in actual.sources.items
    )


@pytest.mark.parametrize(
    ("permission", "decision"),
    (
        ("display", LicensePermission.DENIED),
        ("store", LicensePermission.DENIED),
        ("display", LicensePermission.UNKNOWN),
        ("store", LicensePermission.UNKNOWN),
    ),
)
def test_current_license_denial_blocks_result_parser_and_cached_cursor(
    seeded_history: SeededHistory,
    monkeypatch: pytest.MonkeyPatch,
    permission: Literal["display", "store"],
    decision: LicensePermission,
) -> None:
    case = case_for(seeded_history)
    prepare_performance(case)
    first = read(
        service_for(case), case.principal, case.account_id, q.IntelligenceKind.PERFORMANCE, limit=1
    )
    assert isinstance(first, q.IntelligenceDataQuality) and first.sources.next_cursor
    assert first.selection is not None and first.selection.input_id is not None
    # Find the license from the actual selected capture, not an unrelated owner source.
    with case.sessions() as session:
        identifier = session.scalar(
            select(hm.HistoricalDependencyModel.license_version_id)
            .where(
                hm.HistoricalDependencyModel.input_id == first.selection.input_id,
                hm.HistoricalDependencyModel.license_version_id.is_not(None),
            )
            .limit(1)
        )
        assert identifier is not None
        original = license_view(session.get_one(ProviderLicenseVersionModel, identifier))
    sources = PostgresSourceService(sessions=case.sessions, cursor_signing_key=CURSOR_KEY)
    denied = replace(
        original,
        id=str(uuid4()),
        version="quality-denied-" + uuid4().hex,
        effective_at=datetime.now(UTC),
        display=decision if permission == "display" else original.display,
        store=decision if permission == "store" else original.store,
    )

    def register(license: SourceLicense) -> None:
        asyncio.run(
            sources.register_source_license(
                case.principal,
                license,
                idempotency_key=str(uuid4()),
                correlation_id="quality-license-fixture",
            )
        )

    register(denied)
    try:
        monkeypatch.setattr(
            implementation,
            "decode_metrics",
            lambda *args: pytest.fail("license checked after parser"),
        )
        actual = read(
            service_for(case),
            case.principal,
            case.account_id,
            q.IntelligenceKind.PERFORMANCE,
            cursor=first.sources.next_cursor,
            limit=1,
        )
        assert isinstance(actual, q.IntelligenceDataQuality)
        assert (
            actual.selection == first.selection
            and actual.sources.exact_total == first.sources.exact_total
        )
        assert all(
            row.current_usability == "blocked" and row.recorded_quality is None
            for row in actual.metrics
        )
    finally:
        register(
            replace(
                original,
                id=str(uuid4()),
                version="quality-restored-" + uuid4().hex,
                effective_at=datetime.now(UTC),
            )
        )


def large_valuation(case: HistoryReportCase, count: int = 120) -> UUID:
    """Synthetic normalized unavailable valuation; cash identities exercise paging.

    No cash totals or computed investment values are invented by this fixture.
    Every child has a genuine portfolio_snapshot FK and an explicit zero cash fact.
    """
    now = datetime.now(UTC)
    identity, calculation = uuid4(), uuid4()
    digest = sha256(str(identity).encode()).hexdigest()
    with case.sessions() as session, session.begin():
        session.add(
            CalculationRunModel(
                id=calculation,
                broker_account_id=case.account_id,
                calculation_name="quality-paging-fixture",
                version="1",
                input_schema_version="1",
                output_schema_version="1",
                input_fingerprint=digest,
                output_fingerprint=digest,
                calculated_at=now,
                valuation_at=now,
                source_cutoff_at=now,
                reporting_currency="EUR",
                method="synthetic unavailable valuation",
                assumptions=[],
                options={},
                input_ids=[],
                quality_state="partial",
                coverage={},
                warnings=[],
                missing_inputs=["valuation_missing"],
                created_at=now,
            )
        )
        session.flush()
        session.add(
            PortfolioSnapshotModel(
                id=identity,
                broker_account_id=case.account_id,
                calculation_run_id=calculation,
                valuation_at=now,
                source_cutoff_at=now,
                reporting_currency="EUR",
                calculation_version="quality-fixture-1",
                quality_state="partial",
                coverage={},
                warnings=[],
                created_at=now,
            )
        )
        session.flush()
        for index in range(count):
            currency = "Q" + chr(65 + index // 26) + chr(65 + index % 26)
            session.add(
                SnapshotCashModel(
                    id=uuid4(),
                    snapshot_id=identity,
                    amount=Decimal(0),
                    currency=currency,
                    quality_state="partial",
                    value_origin="derived",
                    provenance={},
                )
            )
    return identity


def test_more_than_100_sources_pin_one_selection_while_a_newer_run_arrives(
    seeded_history: SeededHistory,
) -> None:
    case = case_for(seeded_history)
    principal = provision(case, BASE_SCOPES)
    selected = large_valuation(case)
    service = service_for(case)
    first = read(service, principal, case.account_id, limit=100)
    assert isinstance(first, q.IntelligenceDataQuality) and first.selection is not None
    assert first.selection.id == selected
    assert first.sources.exact_total == 122 and len(first.sources.items) == 100
    assert first.sources.next_cursor
    newer = large_valuation(case, 1)
    tail = read(
        service_for(case), principal, case.account_id, cursor=first.sources.next_cursor, limit=100
    )
    assert isinstance(tail, q.IntelligenceDataQuality)
    assert tail.selection == first.selection and tail.selection_at == first.selection_at
    assert tail.sources.exact_total == 122 and tail.sources.next_cursor is None
    identities = [source.identity for source in (*first.sources.items, *tail.sources.items)]
    assert len(identities) == len(set(identities)) == 122
    latest = read(service, principal, case.account_id)
    assert isinstance(latest, q.IntelligenceDataQuality) and latest.selection is not None
    assert latest.selection.id == newer


def test_cursor_binds_kind_current_optional_scope_projection_and_typed_parent(
    seeded_history: SeededHistory,
) -> None:
    case = case_for(seeded_history)
    large_valuation(case)
    service = service_for(case)
    first = read(service, case.principal, case.account_id, limit=1)
    assert isinstance(first, q.IntelligenceDataQuality) and first.sources.next_cursor
    baseline = provision(case, BASE_SCOPES)
    with pytest.raises(CursorValidationError):
        read(service, baseline, case.account_id, cursor=first.sources.next_cursor)
    with pytest.raises(CursorValidationError):
        read(
            service,
            baseline,
            case.account_id,
            q.IntelligenceKind.PERFORMANCE,
            cursor=first.sources.next_cursor,
        )
    with case.sessions() as session:
        bindings = session.scalars(
            select(Binding).where(Binding.account_id == case.account_id)
        ).all()
        assert bindings
        for binding in bindings:
            generic = session.get_one(CollectionQuerySnapshotModel, binding.collection_id)
            assert generic.source_snapshot_id is None
            if binding.analytics_kind == "valuation":
                assert (
                    binding.valuation_snapshot_id is not None and binding.analytics_run_id is None
                )


def test_quota_plus_one_rolls_back_generated_binding_and_members_atomically(
    seeded_history: SeededHistory,
) -> None:
    case = case_for(seeded_history)
    large_valuation(case)
    before = None
    with case.sessions() as session:
        before = tuple(
            session.scalar(select(func.count()).select_from(model)) for model in (Binding, Member)
        )
    # A different principal scope fingerprint prevents reuse of another traversal.
    principal = provision(case, BASE_SCOPES)
    service = service_for(case, max_active_collection_members_per_owner=121)
    with pytest.raises(CollectionSnapshotCapacityError):
        read(service, principal, case.account_id)
    with case.sessions() as session:
        assert (
            tuple(
                session.scalar(select(func.count()).select_from(model))
                for model in (Binding, Member)
            )
            == before
        )


def test_collection_delete_removes_only_temporary_identity_rows(
    seeded_history: SeededHistory,
) -> None:
    case = case_for(seeded_history)
    selected = large_valuation(case, 2)
    result = read(service_for(case), case.principal, case.account_id)
    assert isinstance(result, q.IntelligenceDataQuality)
    with case.sessions() as session, session.begin():
        binding = session.scalar(select(Binding).where(Binding.valuation_snapshot_id == selected))
        assert binding is not None
        collection = binding.collection_id
        session.execute(
            delete(CollectionQuerySnapshotModel).where(
                CollectionQuerySnapshotModel.id == collection
            )
        )
        assert (
            session.scalar(
                select(func.count()).select_from(Member).where(Member.collection_id == collection)
            )
            == 0
        )
        assert session.get(PortfolioSnapshotModel, selected) is not None
        assert (
            session.scalar(
                select(func.count())
                .select_from(SnapshotCashModel)
                .where(SnapshotCashModel.snapshot_id == selected)
            )
            == 2
        )


def test_corrupt_collection_identity_invalidates_cursor_without_echo(
    seeded_history: SeededHistory,
) -> None:
    case = case_for(seeded_history)
    selected = large_valuation(case, 2)
    service = service_for(case)
    first = read(service, case.principal, case.account_id, limit=1)
    assert isinstance(first, q.IntelligenceDataQuality) and first.sources.next_cursor
    with case.sessions() as session, session.begin():
        collection = session.scalar(
            select(Binding.collection_id).where(Binding.valuation_snapshot_id == selected)
        )
        member = session.scalar(
            select(Member)
            .where(Member.collection_id == collection)
            .order_by(Member.ordinal)
            .limit(1)
        )
        assert member is not None
        member_id, original_id = member.id, member.source_id
        member.source_id = uuid4()
    try:
        with pytest.raises(CursorValidationError):
            read(service, case.principal, case.account_id, cursor=first.sources.next_cursor)
    finally:
        with case.sessions() as session, session.begin():
            session.execute(
                update(Member).where(Member.id == member_id).values(source_id=original_id)
            )
