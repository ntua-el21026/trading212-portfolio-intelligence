"""Real SQL source retention, shared evidence and bounded retry without financial decoding."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, event, select, text
from sqlalchemy.orm import Session
from trading212_domain.scenario import ScenarioSensitivityVersionPin
from trading212_persistence.report_authorization import authorize_report_request
from trading212_persistence.scenario_source_models import (
    ScenarioSensitivityEvidenceLinkModel,
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityEvidencePayloadModel,
    ScenarioSensitivityRetentionModel,
    ScenarioSensitivityVersionModel,
    ScenarioSensitivityVersionPayloadModel,
)
from trading212_persistence.scenario_source_retention import expire_scenario_sensitivity_payloads
from trading212_persistence.scenario_source_store import ScenarioSourceStore
from trading212_persistence.scenario_store_types import (
    ScenarioStorageError,
    ScenarioStorageErrorCode,
)
from trading212_persistence.source_models import ProviderLicenseVersionModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_security.principals import Scope
from trading212_worker.xray_seed import XRAY_CURSOR_KEY

from tests.integration.test_migrations import _add_identity_graph
from tests.integration.test_phase3_scenario_schema import NOW, source
from tests.integration.test_phase3_scenario_schema import database_engine as database_engine
from tests.integration.test_phase3_scenario_schema import scope as scope
from tests.integration.test_scenario_runs_postgres import ScenarioCase
from tests.integration.test_scenario_runs_postgres import scenario_case as scenario_case
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = [pytest.mark.integration, pytest.mark.migrations]


def publish(session: Session, version: ScenarioSensitivityVersionModel) -> None:
    version.sealed = True
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def restrict(
    session: Session,
    version: ScenarioSensitivityVersionModel,
    *,
    store: str = "allowed",
    days: int = 7,
    effective_at: datetime = NOW,
) -> None:
    session.add(
        ProviderLicenseVersionModel(
            id=uuid4(),
            owner_id=version.owner_id,
            provider_id=version.provider_id,
            version_number=2,
            version="2",
            effective_at=effective_at,
            store_permission=store,
            display_permission="allowed",
            report_permission="allowed",
            export_permission="allowed",
            retention_days=days,
            attribution="Synthetic current license",
            evidence_key="synthetic",
            created_at=NOW,
        )
    )
    session.flush()


def pass_cleanup(
    session: Session,
    owner: UUID,
    *,
    at: datetime = NOW,
    budget: SourcePurgeBudget | None = None,
    erase: bool = False,
) -> bool:
    return expire_scenario_sensitivity_payloads(
        session,
        at=at,
        owner=owner,
        budget=budget or SourcePurgeBudget(),
        erase=erase,
    )


def marker(
    session: Session, version: ScenarioSensitivityVersionModel
) -> ScenarioSensitivityRetentionModel:
    value = session.scalar(
        select(ScenarioSensitivityRetentionModel).where(
            ScenarioSensitivityRetentionModel.version_id == version.id,
            ScenarioSensitivityRetentionModel.owner_id == version.owner_id,
        )
    )
    assert value is not None
    return value


def physical_version(session: Session, version: ScenarioSensitivityVersionModel) -> UUID | None:
    return session.scalar(
        select(ScenarioSensitivityVersionPayloadModel.id).where(
            ScenarioSensitivityVersionPayloadModel.version_id == version.id,
        )
    )


@pytest.mark.parametrize("permission,days,later", [("denied", 7, 0), ("allowed", 1, 2)])
def test_current_rights_and_tightened_deadline_remove_source_payload_only(
    scope: tuple[Session, UUID, UUID, UUID],
    permission: str,
    days: int,
    later: int,
) -> None:
    session, owner, _, _ = scope
    version, _ = source(session, owner)
    publish(session, version)
    restrict(session, version, store=permission, days=days)
    at = NOW + timedelta(days=later)
    assert pass_cleanup(session, owner, at=at)
    assert physical_version(session, version) is None
    assert marker(session, version).completed_at == at
    assert session.get(ScenarioSensitivityVersionModel, version.id) is version
    assert version.content_digest == "b" * 64
    assert pass_cleanup(session, owner, at=at)
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_future_license_and_foreign_owner_do_not_remove_permitted_payload(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, _, _ = scope
    version, _ = source(session, owner)
    publish(session, version)
    restrict(session, version, store="denied", effective_at=NOW + timedelta(days=1))
    assert pass_cleanup(session, owner)
    assert physical_version(session, version) is not None
    assert pass_cleanup(session, uuid4(), at=NOW + timedelta(days=10))
    assert physical_version(session, version) is not None
    assert pass_cleanup(session, owner, at=NOW + timedelta(days=1))
    assert physical_version(session, version) is None


def test_zero_byte_allowance_marks_without_claiming_deletion_and_retry_completes(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, _, _ = scope
    version, _ = source(session, owner)
    publish(session, version)
    zero = SourcePurgeBudget(bytes_removed=0)
    at = NOW + timedelta(days=8)
    assert not pass_cleanup(session, owner, at=at, budget=zero)
    assert physical_version(session, version) is not None
    assert marker(session, version).completed_at is None
    assert zero.bytes_removed == 0 and zero.rows_removed == 4096
    assert pass_cleanup(session, owner, at=at)
    assert marker(session, version).completed_at == at
    assert physical_version(session, version) is None


def shared(
    session: Session,
    owner: UUID,
) -> tuple[ScenarioSensitivityVersionModel, ScenarioSensitivityVersionModel, UUID]:
    first, _ = source(session, owner, evidence_count=1)
    second, _ = source(session, owner, evidence_count=1)
    restrict(session, first, days=1)
    evidence = ScenarioSensitivityEvidenceModel(
        id=uuid4(),
        owner_id=owner,
        provider_id=second.provider_id,
        license_version_id=second.license_version_id,
        source_record_id=uuid4(),
        content_digest="e" * 64,
        created_at=NOW,
    )
    session.add(evidence)
    session.flush()
    payload = ScenarioSensitivityEvidencePayloadModel(
        id=uuid4(),
        owner_id=owner,
        evidence_id=evidence.id,
        effective_at=NOW,
        first_known_at=NOW,
        adapter_id="synthetic",
        adapter_version="1",
        transformation="identity_local_simple_return_v1",
        canonical_payload=b"synthetic retained shared source proof",
        created_at=NOW,
    )
    session.add(payload)
    session.flush()
    for version in (first, second):
        session.add(
            ScenarioSensitivityEvidenceLinkModel(
                id=uuid4(),
                owner_id=owner,
                version_id=version.id,
                evidence_id=evidence.id,
                observation_id=None,
                created_at=NOW,
            )
        )
    session.flush()
    first.sealed = second.sealed = True
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    return first, second, payload.id


def test_shared_evidence_keeps_live_sibling_and_expired_sibling_does_not_starve_cleanup(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, _, _ = scope
    first, second, evidence_payload_id = shared(session, owner)
    early = NOW + timedelta(days=2)
    assert not pass_cleanup(session, owner, at=early)
    assert physical_version(session, first) is None
    assert marker(session, first).completed_at is None
    assert physical_version(session, second) is not None
    assert session.get(ScenarioSensitivityEvidencePayloadModel, evidence_payload_id) is not None
    assert (
        session.scalar(
            select(ScenarioSensitivityRetentionModel.id).where(
                ScenarioSensitivityRetentionModel.version_id == second.id,
            )
        )
        is None
    )
    # Either UUID ordering must converge: the sweep advances past pending first
    # to mark second, and the next invocation can finish first's shared proof.
    later = NOW + timedelta(days=8)
    for _ in range(3):
        if pass_cleanup(session, owner, at=later):
            break
    else:
        pytest.fail("Shared source retention did not converge")
    session.expire_all()
    assert session.get(ScenarioSensitivityEvidencePayloadModel, evidence_payload_id) is None
    assert marker(session, first).completed_at is not None
    assert marker(session, second).completed_at is not None
    assert pass_cleanup(session, owner, at=later)
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_restricted_evidence_license_invalidates_every_linked_source_version(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, _, _ = scope
    first, second, evidence_payload_id = shared(session, owner)
    # First has a different provider: only its immutable evidence link connects
    # it to the newly denied provider. Its own one-day allowance is still valid.
    assert first.provider_id != second.provider_id
    restrict(session, second, store="denied")
    for _ in range(3):
        if pass_cleanup(session, owner):
            break
    else:
        pytest.fail("Evidence restriction did not invalidate every linked version")
    session.expire_all()
    assert session.get(ScenarioSensitivityEvidencePayloadModel, evidence_payload_id) is None
    assert marker(session, first).completed_at == NOW


def test_explicit_owner_erasure_drains_unexpired_payloads_under_same_allowance(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, _, _ = scope
    version, _ = source(session, owner)
    publish(session, version)
    assert pass_cleanup(session, owner, erase=True)
    assert physical_version(session, version) is None
    assert marker(session, version).reason == "owner_erasure"
    with pytest.raises(ValueError, match="explicit owner"):
        expire_scenario_sensitivity_payloads(
            session,
            at=NOW,
            budget=SourcePurgeBudget(),
            erase=True,
        )


def test_busy_owner_is_skipped_without_deleting_source_payload(database_engine: Engine) -> None:
    with Session(database_engine) as session:
        owner, *_ = _add_identity_graph(session)
        version, payload = source(session, owner)
        version.sealed = True
        session.flush()
        payload_id = payload.id
        session.commit()
    with Session(database_engine) as holder, Session(database_engine) as cleanup:
        holder.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"sources:{owner}"},
        )
        cleanup.execute(text("SET LOCAL lock_timeout = '1s'"))
        assert not pass_cleanup(cleanup, owner, at=NOW + timedelta(days=8))
        assert cleanup.get(ScenarioSensitivityVersionPayloadModel, payload_id) is not None
        cleanup.rollback()
        holder.rollback()
        assert pass_cleanup(cleanup, owner, at=NOW + timedelta(days=8))
        cleanup.commit()


def require_denied_before_payload_read(
    case: ScenarioCase,
    version_id: UUID,
    *,
    at: datetime,
) -> None:
    store = ScenarioSourceStore(case.sessions, cursor_signing_key=XRAY_CURSOR_KEY, clock=lambda: at)
    with case.sessions() as session, session.begin():
        version = session.get_one(ScenarioSensitivityVersionModel, version_id)
        pin = ScenarioSensitivityVersionPin(
            version_id=version.id,
            content_digest=version.content_digest,
            driver_id=version.driver_id,
            driver_definition_version_id=version.driver_definition_version_id,
        )
        assert version.expires_at > at
        assert (
            session.scalar(
                select(ScenarioSensitivityRetentionModel.id).where(
                    ScenarioSensitivityRetentionModel.version_id == version.id,
                )
            )
            is None
        )
        auth = authorize_report_request(
            session,
            case.principal,
            account_id=case.command.account_id,
            required_scopes=frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ}),
            now=at,
        )

        def no_payload_select(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: object,
        ) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                assert not any(
                    table in statement
                    for table in (
                        "scenario_sensitivity_version_payloads",
                        "scenario_sensitivity_observation_payloads",
                        "scenario_sensitivity_evidence_payloads",
                    )
                ), "An expired original source must be rejected before payload selection"

        event.listen(case.engine, "before_cursor_execute", no_payload_select)
        try:
            with pytest.raises(ScenarioStorageError) as failure:
                store.read_capture(session, auth, (pin,), retained_at=at)
            assert failure.value.code is ScenarioStorageErrorCode.RUN_EXPIRED
        finally:
            event.remove(case.engine, "before_cursor_execute", no_payload_select)


async def test_original_version_deadline_denies_new_copy_before_cleanup(
    scenario_case: ScenarioCase,
) -> None:
    case = scenario_case
    owner = UUID(case.principal.owner_id)
    with case.sessions() as session, session.begin():
        version, _ = source(session, owner)
        publish(session, version)
        restrict(session, version, days=1)
        identifier = version.id
    require_denied_before_payload_read(case, identifier, at=NOW + timedelta(days=2))


async def test_older_shared_evidence_lifetime_cannot_refresh_via_new_source_version(
    scenario_case: ScenarioCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.integration import test_phase3_scenario_schema as schema

    case = scenario_case
    owner = UUID(case.principal.owner_id)
    with case.sessions() as session, session.begin():
        original, _ = source(session, owner, evidence_count=1)
        evidence = ScenarioSensitivityEvidenceModel(
            id=uuid4(),
            owner_id=owner,
            provider_id=original.provider_id,
            license_version_id=original.license_version_id,
            source_record_id=uuid4(),
            content_digest="e" * 64,
            created_at=NOW,
        )
        session.add(evidence)
        session.flush()
        session.add(
            ScenarioSensitivityEvidencePayloadModel(
                id=uuid4(),
                owner_id=owner,
                evidence_id=evidence.id,
                effective_at=NOW,
                first_known_at=NOW,
                adapter_id="synthetic",
                adapter_version="1",
                transformation="identity_local_simple_return_v1",
                canonical_payload=b"synthetic old evidence; must never be decoded",
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            ScenarioSensitivityEvidenceLinkModel(
                id=uuid4(),
                owner_id=owner,
                version_id=original.id,
                observation_id=None,
                evidence_id=evidence.id,
                created_at=NOW,
            )
        )
        session.flush()
        publish(session, original)
        # V2 is inserted later; immutable created_at fields are never rewritten.
        with monkeypatch.context() as fixture_clock:
            fixture_clock.setattr(schema, "NOW", NOW + timedelta(days=2))
            newer, _ = source(session, owner, evidence_count=1)
        session.add(
            ScenarioSensitivityEvidenceLinkModel(
                id=uuid4(),
                owner_id=owner,
                version_id=newer.id,
                observation_id=None,
                evidence_id=evidence.id,
                created_at=NOW + timedelta(days=2),
            )
        )
        session.flush()
        publish(session, newer)
        restrict(session, original, days=2, effective_at=NOW + timedelta(days=3))
        assert newer.created_at > evidence.created_at
        identifier = newer.id
    require_denied_before_payload_read(case, identifier, at=NOW + timedelta(days=3))
